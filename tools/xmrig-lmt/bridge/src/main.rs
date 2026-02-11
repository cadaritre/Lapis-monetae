use std::{net::SocketAddr, sync::Arc, time::Duration};

use clap::Parser;
use kaspa_consensus_core::{hashing, header::Header};
use kaspa_grpc_client::GrpcClient;
use kaspa_math::Uint256;
use kaspa_rpc_core::{
    api::rpc::RpcApi,
    model::{
        address::RpcAddress,
        message::{GetBlockTemplateRequest, RpcExtraData, SubmitBlockRequest},
        RpcRawBlock, RpcRawHeader,
    },
};
use kaspa_utils::hex::{FromHex, ToHex};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use futures_util::{SinkExt, StreamExt};
use tokio::{net::TcpListener, sync::Mutex};
use tokio_util::codec::{FramedRead, FramedWrite, LinesCodec};

#[derive(Parser, Debug)]
#[command(author, version, about)]
struct Args {
    /// Stratum listen address (host:port)
    #[arg(long, default_value = "0.0.0.0:3333")]
    listen: String,
    /// gRPC RPC URL, e.g. grpc://127.0.0.1:26110
    #[arg(long, default_value = "grpc://127.0.0.1:26110")]
    rpc_url: String,
    /// LMT pay address for coinbase rewards
    #[arg(long)]
    pay_address: String,
    /// Extra data in hex (optional)
    #[arg(long, default_value = "")]
    extra_data_hex: String,
    /// Allow non-DAA blocks when submitting (useful for tests)
    #[arg(long, default_value_t = true)]
    allow_non_daa: bool,
    /// Template refresh interval in ms
    #[arg(long, default_value_t = 5000)]
    refresh_ms: u64,
}

#[derive(Debug, Clone)]
struct Template {
    job_id: u64,
    block: RpcRawBlock,
    pre_pow_hash_hex: String,
    timestamp: u64,
    bits_hex: String,
    target_hex: String,
}

#[derive(Debug, Deserialize)]
struct StratumRequest {
    id: Option<u64>,
    method: String,
    params: Option<Value>,
}

#[derive(Debug, Serialize)]
struct StratumResponse<'a> {
    id: u64,
    result: &'a Value,
    error: Option<Value>,
}

#[derive(Debug, Serialize)]
struct StratumNotification<'a> {
    method: &'a str,
    params: Value,
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args = Args::parse();
    let pay_address = RpcAddress::try_from(args.pay_address.as_str())?;
    let extra_data: RpcExtraData = if args.extra_data_hex.is_empty() {
        Vec::new()
    } else {
        Vec::<u8>::from_hex(args.extra_data_hex.as_str())?
    };

    let client = GrpcClient::connect(args.rpc_url.clone()).await?;
    client.start(None).await;

    let listener = TcpListener::bind(&args.listen).await?;
    println!("LMT Stratum bridge listening on {}", args.listen);

    let client = Arc::new(client);
    let extra_data = Arc::new(extra_data);
    let pay_address = Arc::new(pay_address);
    let refresh = Duration::from_millis(args.refresh_ms);
    let allow_non_daa = args.allow_non_daa;

    loop {
        let (stream, addr) = listener.accept().await?;
        let client = client.clone();
        let extra_data = extra_data.clone();
        let pay_address = pay_address.clone();
        tokio::spawn(async move {
            if let Err(err) =
                handle_client(stream, addr, client, pay_address, extra_data, allow_non_daa, refresh).await
            {
                eprintln!("client {} error: {}", addr, err);
            }
        });
    }
}

async fn handle_client(
    stream: tokio::net::TcpStream,
    addr: SocketAddr,
    client: Arc<GrpcClient>,
    pay_address: Arc<RpcAddress>,
    extra_data: Arc<RpcExtraData>,
    allow_non_daa: bool,
    refresh: Duration,
) -> Result<(), Box<dyn std::error::Error>> {
    let (reader, writer) = stream.into_split();
    let mut lines = FramedRead::new(reader, LinesCodec::new());
    let mut sink = FramedWrite::new(writer, LinesCodec::new());
    let template_state = Arc::new(Mutex::new(None::<Template>));
    let mut job_counter = 0u64;

    let mut refresh_timer = tokio::time::interval(refresh);
    refresh_timer.tick().await;

    loop {
        tokio::select! {
            maybe_line = lines.next() => {
                let Some(line) = maybe_line else { break; };
                let line = line?;
                let req: StratumRequest = match serde_json::from_str(&line) {
                    Ok(req) => req,
                    Err(_) => continue,
                };
                match req.method.as_str() {
                    "mining.subscribe" => {
                        let result = serde_json::json!({ "protocol": "lmt-stratum/1.0" });
                        send_response(&mut sink, req.id, result).await?;
                        if template_state.lock().await.is_none() {
                            let template = fetch_template(&client, &pay_address, &extra_data, &mut job_counter).await?;
                            *template_state.lock().await = Some(template.clone());
                            send_notify(&mut sink, &template).await?;
                        }
                    }
                    "mining.authorize" => {
                        let result = serde_json::json!(true);
                        send_response(&mut sink, req.id, result).await?;
                    }
                    "mining.submit" => {
                        let params = req.params.unwrap_or(Value::Null);
                        let submit = parse_submit(params)?;
                        let mut template_guard = template_state.lock().await;
                        let Some(template) = template_guard.clone() else {
                            let result = serde_json::json!(false);
                            send_response(&mut sink, req.id, result).await?;
                            continue;
                        };
                        if submit.job_id != template.job_id {
                            let result = serde_json::json!(false);
                            send_response(&mut sink, req.id, result).await?;
                            continue;
                        }
                        let mut block = template.block.clone();
                        block.header.nonce = submit.nonce;
                        if let Some(ts) = submit.timestamp {
                            block.header.timestamp = ts;
                        }
                        let submit_req = SubmitBlockRequest::new(block, allow_non_daa);
                        let submit_res = client.submit_block_call(submit_req).await;
                        let result = serde_json::json!(submit_res.is_ok());
                        send_response(&mut sink, req.id, result).await?;
                    }
                    _ => {
                        let result = serde_json::json!(null);
                        send_response(&mut sink, req.id, result).await?;
                    }
                }
            }
            _ = refresh_timer.tick() => {
                let template = fetch_template(&client, &pay_address, &extra_data, &mut job_counter).await?;
                *template_state.lock().await = Some(template.clone());
                send_notify(&mut sink, &template).await?;
            }
        }
    }

    println!("client {} disconnected", addr);
    Ok(())
}

async fn fetch_template(
    client: &GrpcClient,
    pay_address: &RpcAddress,
    extra_data: &RpcExtraData,
    job_counter: &mut u64,
) -> Result<Template, Box<dyn std::error::Error>> {
    let response = client
        .get_block_template_call(GetBlockTemplateRequest::new(pay_address.clone(), extra_data.clone()))
        .await?;
    let block = response.block;
    let header = raw_header_to_header(&block.header);
    let pre_pow_hash = hashing::header::hash_override_nonce_time(&header, 0, 0);
    let bits_hex = format!("0x{:08x}", block.header.bits);
    let target = Uint256::from_compact_target_bits(block.header.bits);
    let target_le = target.to_le_bytes();
    let target_hex = target_le[24..32].to_vec().to_hex();
    *job_counter += 1;
    Ok(Template {
        job_id: *job_counter,
        pre_pow_hash_hex: pre_pow_hash.as_bytes().to_vec().to_hex(),
        timestamp: block.header.timestamp,
        bits_hex,
        target_hex,
        block,
    })
}

fn raw_header_to_header(header: &RpcRawHeader) -> Header {
    Header::new_finalized(
        header.version,
        header.parents_by_level.clone(),
        header.hash_merkle_root,
        header.accepted_id_merkle_root,
        header.utxo_commitment,
        header.timestamp,
        header.bits,
        header.nonce,
        header.daa_score,
        header.blue_work,
        header.blue_score,
        header.pruning_point,
    )
}

async fn send_response(
    sink: &mut FramedWrite<tokio::net::tcp::OwnedWriteHalf, LinesCodec>,
    id: Option<u64>,
    result: Value,
) -> Result<(), Box<dyn std::error::Error>> {
    if let Some(id) = id {
        let response = StratumResponse { id, result: &result, error: None };
        let line = serde_json::to_string(&response)?;
        sink.send(line).await?;
    }
    Ok(())
}

async fn send_notify(
    sink: &mut FramedWrite<tokio::net::tcp::OwnedWriteHalf, LinesCodec>,
    template: &Template,
) -> Result<(), Box<dyn std::error::Error>> {
    let params = serde_json::json!([
        template.job_id.to_string(),
        template.pre_pow_hash_hex,
        template.timestamp,
        template.bits_hex,
        template.target_hex
    ]);
    let notification = StratumNotification { method: "mining.notify", params };
    let line = serde_json::to_string(&notification)?;
    sink.send(line).await?;
    Ok(())
}

#[derive(Debug)]
struct SubmitParams {
    job_id: u64,
    nonce: u64,
    timestamp: Option<u64>,
}

fn parse_submit(params: Value) -> Result<SubmitParams, Box<dyn std::error::Error>> {
    let params = params.as_array().cloned().unwrap_or_default();
    if params.len() < 3 {
        return Err("submit requires at least 3 params".into());
    }
    let job_id = params[1].as_str().ok_or("job_id missing")?.parse::<u64>()?;
    let nonce_str = params[2].as_str().ok_or("nonce missing")?;
    let nonce_str = nonce_str.trim_start_matches("0x");
    let nonce = u64::from_str_radix(nonce_str, 16)?;
    let timestamp = params.get(3).and_then(|v| v.as_u64()).filter(|ts| *ts > 0);
    Ok(SubmitParams { job_id, nonce, timestamp })
}
