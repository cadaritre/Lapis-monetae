import json
import queue
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
from tkinter.scrolledtext import ScrolledText

CONFIG_PATH = Path(__file__).with_name("config.json")


def load_config():
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def save_config(data):
    CONFIG_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


class BridgeGui:
    def __init__(self, root):
        self.root = root
        self.root.title("LMT Stratum Bridge GUI")
        self.process = None
        self.log_queue = queue.Queue()

        config = load_config()

        self.bridge_path = tk.StringVar(value=config.get("bridge_path", ""))
        self.listen = tk.StringVar(value=config.get("listen", "0.0.0.0:3333"))
        self.rpc_url = tk.StringVar(value=config.get("rpc_url", "grpc://127.0.0.1:26110"))
        self.pay_address = tk.StringVar(value=config.get("pay_address", ""))
        self.extra_data_hex = tk.StringVar(value=config.get("extra_data_hex", ""))
        self.allow_non_daa = tk.BooleanVar(value=config.get("allow_non_daa", True))
        self.refresh_ms = tk.StringVar(value=str(config.get("refresh_ms", 5000)))
        self.xmrig_path = tk.StringVar(value=config.get("xmrig_path", ""))
        self.xmrig_url = tk.StringVar(value=config.get("xmrig_url", "stratum+tcp://127.0.0.1:3333"))
        self.xmrig_extra = tk.StringVar(value=config.get("xmrig_extra", ""))
        self.start_miner_with_bridge = tk.BooleanVar(value=config.get("start_miner_with_bridge", False))

        self._build_layout()
        self._start_log_pump()

    def _build_layout(self):
        frame = tk.Frame(self.root, padx=10, pady=10)
        frame.pack(fill=tk.BOTH, expand=True)

        row = 0
        self._add_row(frame, row, "Bridge binary", self.bridge_path, browse=True)
        row += 1
        self._add_row(frame, row, "Listen", self.listen)
        row += 1
        self._add_row(frame, row, "RPC URL", self.rpc_url)
        row += 1
        self._add_row(frame, row, "Pay address", self.pay_address)
        row += 1
        self._add_row(frame, row, "Extra data (hex)", self.extra_data_hex)
        row += 1
        self._add_row(frame, row, "Refresh ms", self.refresh_ms)
        row += 1

        checkbox = tk.Checkbutton(frame, text="Allow non-DAA blocks", variable=self.allow_non_daa)
        checkbox.grid(row=row, column=0, columnspan=3, sticky="w", pady=(2, 8))
        row += 1

        tk.Label(frame, text="XMRig (fork) settings").grid(row=row, column=0, columnspan=3, sticky="w", pady=(8, 2))
        row += 1
        self._add_row(frame, row, "XMRig binary", self.xmrig_path, browse=True, browse_target="xmrig")
        row += 1
        self._add_row(frame, row, "XMRig URL", self.xmrig_url)
        row += 1
        self._add_row(frame, row, "XMRig extra args", self.xmrig_extra)
        row += 1
        miner_checkbox = tk.Checkbutton(frame, text="Start miner with bridge", variable=self.start_miner_with_bridge)
        miner_checkbox.grid(row=row, column=0, columnspan=3, sticky="w", pady=(2, 8))
        row += 1

        btn_frame = tk.Frame(frame)
        btn_frame.grid(row=row, column=0, columnspan=3, sticky="w")
        tk.Button(btn_frame, text="Start", command=self.start_bridge).pack(side=tk.LEFT, padx=(0, 6))
        tk.Button(btn_frame, text="Stop", command=self.stop_bridge).pack(side=tk.LEFT, padx=(0, 6))
        tk.Button(btn_frame, text="Save", command=self.save_settings).pack(side=tk.LEFT)
        row += 1

        self.log = ScrolledText(frame, height=15, state=tk.DISABLED)
        self.log.grid(row=row, column=0, columnspan=3, sticky="nsew", pady=(10, 0))

        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(row, weight=1)

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _add_row(self, frame, row, label, variable, browse=False, browse_target="bridge"):
        tk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=2)
        entry = tk.Entry(frame, textvariable=variable, width=60)
        entry.grid(row=row, column=1, sticky="ew", pady=2)
        if browse:
            tk.Button(frame, text="Browse", command=lambda: self.browse_binary(browse_target)).grid(
                row=row, column=2, sticky="w", padx=(6, 0)
            )

    def browse_binary(self, target):
        path = filedialog.askopenfilename(title="Select bridge binary")
        if path:
            if target == "bridge":
                self.bridge_path.set(path)
            else:
                self.xmrig_path.set(path)

    def append_log(self, text):
        self.log.configure(state=tk.NORMAL)
        self.log.insert(tk.END, text + "\n")
        self.log.configure(state=tk.DISABLED)
        self.log.see(tk.END)

    def _start_log_pump(self):
        def pump():
            while True:
                try:
                    line = self.log_queue.get_nowait()
                except queue.Empty:
                    break
                self.append_log(line)
            self.root.after(100, pump)

        self.root.after(100, pump)

    def start_bridge(self):
        if self.process:
            messagebox.showinfo("Bridge", "Bridge is already running.")
            return

        bridge_path = self.bridge_path.get().strip()
        if not bridge_path:
            messagebox.showerror("Bridge", "Please select the bridge binary.")
            return

        cmd = [
            bridge_path,
            "--listen",
            self.listen.get().strip(),
            "--rpc-url",
            self.rpc_url.get().strip(),
            "--pay-address",
            self.pay_address.get().strip(),
            "--refresh-ms",
            self.refresh_ms.get().strip(),
        ]
        if self.extra_data_hex.get().strip():
            cmd += ["--extra-data-hex", self.extra_data_hex.get().strip()]
        if self.allow_non_daa.get():
            cmd += ["--allow-non-daa"]

        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except OSError as exc:
            messagebox.showerror("Bridge", f"Failed to start: {exc}")
            return

        threading.Thread(target=self._read_logs, daemon=True).start()
        self.append_log("Bridge started.")
        if self.start_miner_with_bridge.get():
            self.start_miner()

    def _read_logs(self):
        if not self.process or not self.process.stdout:
            return
        for line in self.process.stdout:
            self.log_queue.put(line.rstrip())

    def stop_bridge(self):
        if not self.process:
            return
        self.process.terminate()
        self.process = None
        self.append_log("Bridge stopped.")
        if getattr(self, "miner_process", None):
            self.stop_miner()

    def start_miner(self):
        if getattr(self, "miner_process", None):
            self.append_log("Miner already running.")
            return
        xmrig_path = self.xmrig_path.get().strip()
        if not xmrig_path:
            self.append_log("XMRig path not set; skipping miner start.")
            return
        url = self.xmrig_url.get().strip()
        address = self.pay_address.get().strip()
        cmd = [xmrig_path, "-o", url, "-u", address, "-p", "x"]
        extra = self.xmrig_extra.get().strip()
        if extra:
            cmd += extra.split()
        try:
            self.miner_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except OSError as exc:
            self.append_log(f"Failed to start miner: {exc}")
            self.miner_process = None
            return
        threading.Thread(target=self._read_miner_logs, daemon=True).start()
        self.append_log("Miner started.")

    def _read_miner_logs(self):
        proc = getattr(self, "miner_process", None)
        if not proc or not proc.stdout:
            return
        for line in proc.stdout:
            self.log_queue.put(f"[miner] {line.rstrip()}")

    def stop_miner(self):
        proc = getattr(self, "miner_process", None)
        if not proc:
            return
        proc.terminate()
        self.miner_process = None
        self.append_log("Miner stopped.")

    def save_settings(self):
        data = {
            "bridge_path": self.bridge_path.get(),
            "listen": self.listen.get(),
            "rpc_url": self.rpc_url.get(),
            "pay_address": self.pay_address.get(),
            "extra_data_hex": self.extra_data_hex.get(),
            "allow_non_daa": self.allow_non_daa.get(),
            "refresh_ms": int(self.refresh_ms.get() or 5000),
            "xmrig_path": self.xmrig_path.get(),
            "xmrig_url": self.xmrig_url.get(),
            "xmrig_extra": self.xmrig_extra.get(),
            "start_miner_with_bridge": self.start_miner_with_bridge.get(),
        }
        save_config(data)
        self.append_log("Settings saved.")

    def on_close(self):
        if self.process:
            self.process.terminate()
        if getattr(self, "miner_process", None):
            self.miner_process.terminate()
        self.root.destroy()


def main():
    root = tk.Tk()
    BridgeGui(root)
    root.mainloop()


if __name__ == "__main__":
    main()
