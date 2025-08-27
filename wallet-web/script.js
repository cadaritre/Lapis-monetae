// Configuración de la wallet
const WALLET_CONFIG = {
    rpcUrl: 'http://localhost:16111', // URL del nodo RPC
    refreshInterval: 10000, // Intervalo de actualización en ms
    defaultAddress: 'lmt1qxy2kg9gj8fxz0mlpl0grpgmmx9c445wsenrdnd',
    networkName: 'Lapis Monetae Devnet'
};

// Estado de la wallet
let walletState = {
    isConnected: false,
    balance: {
        total: 0,
        available: 0,
        pending: 0
    },
    address: WALLET_CONFIG.defaultAddress,
    transactions: [],
    lastUpdate: null
};

// Elementos del DOM
const elements = {
    totalBalance: document.getElementById('totalBalance'),
    availableBalance: document.getElementById('availableBalance'),
    pendingBalance: document.getElementById('pendingBalance'),
    walletAddress: document.getElementById('walletAddress'),
    modalAddress: document.getElementById('modalAddress'),
    transactionsList: document.getElementById('transactionsList'),
    networkStatus: document.querySelector('.network-status'),
    statusDot: document.querySelector('.status-dot'),
    statusText: document.querySelector('.status-text')
};

// Inicialización
document.addEventListener('DOMContentLoaded', function() {
    initializeWallet();
    setupEventListeners();
    startAutoRefresh();
});

// Inicializar la wallet
function initializeWallet() {
    console.log('Inicializando Lapis Monetae Wallet...');
    
    // Establecer dirección por defecto
    elements.walletAddress.textContent = walletState.address;
    elements.modalAddress.textContent = walletState.address;
    
    // Verificar conexión con el nodo
    checkNodeConnection();
    
    // Cargar datos iniciales
    loadWalletData();
    
    // Cargar transacciones de ejemplo
    loadSampleTransactions();
}

// Configurar event listeners
function setupEventListeners() {
    // Cerrar modales al hacer clic fuera
    window.addEventListener('click', function(event) {
        if (event.target.classList.contains('modal')) {
            closeAllModals();
        }
    });
    
    // Tecla Escape para cerrar modales
    document.addEventListener('keydown', function(event) {
        if (event.key === 'Escape') {
            closeAllModals();
        }
    });
}

// Verificar conexión con el nodo
async function checkNodeConnection() {
    try {
        const response = await fetch(`${WALLET_CONFIG.rpcUrl}/network/status`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                jsonrpc: '2.0',
                id: 1,
                method: 'getNetworkStatus',
                params: []
            })
        });
        
        if (response.ok) {
            updateConnectionStatus(true);
            walletState.isConnected = true;
        } else {
            updateConnectionStatus(false);
            walletState.isConnected = false;
        }
    } catch (error) {
        console.log('No se pudo conectar al nodo:', error.message);
        updateConnectionStatus(false);
        walletState.isConnected = false;
    }
}

// Actualizar estado de conexión
function updateConnectionStatus(isConnected) {
    if (isConnected) {
        elements.statusDot.classList.remove('offline');
        elements.statusDot.classList.add('online');
        elements.statusText.textContent = 'Conectado';
        elements.statusText.style.color = 'var(--success-color)';
    } else {
        elements.statusDot.classList.remove('online');
        elements.statusDot.classList.add('offline');
        elements.statusText.textContent = 'Desconectado';
        elements.statusText.style.color = 'var(--error-color)';
    }
}

// Cargar datos de la wallet
async function loadWalletData() {
    if (!walletState.isConnected) {
        console.log('Nodo no conectado, usando datos de ejemplo');
        loadSampleData();
        return;
    }
    
    try {
        // Aquí irían las llamadas reales a la API del nodo
        // Por ahora usamos datos de ejemplo
        loadSampleData();
    } catch (error) {
        console.error('Error al cargar datos de la wallet:', error);
        loadSampleData();
    }
}

// Cargar datos de ejemplo
function loadSampleData() {
    // Simular balance
    walletState.balance = {
        total: 1250.75000000,
        available: 1200.50000000,
        pending: 50.25000000
    };
    
    updateBalanceDisplay();
    updateLastUpdate();
}

// Actualizar display del balance
function updateBalanceDisplay() {
    elements.totalBalance.textContent = walletState.balance.total.toFixed(8);
    elements.availableBalance.textContent = walletState.balance.available.toFixed(8) + ' LMT';
    elements.pendingBalance.textContent = walletState.balance.pending.toFixed(8) + ' LMT';
}

// Actualizar última actualización
function updateLastUpdate() {
    walletState.lastUpdate = new Date();
}

// Cargar transacciones de ejemplo
function loadSampleTransactions() {
    walletState.transactions = [
        {
            id: '1',
            type: 'received',
            amount: 100.00000000,
            address: 'lmt1abc...',
            time: 'Hace 2 horas',
            status: 'confirmed'
        },
        {
            id: '2',
            type: 'sent',
            amount: 25.50000000,
            address: 'lmt1def...',
            time: 'Hace 1 día',
            status: 'confirmed'
        },
        {
            id: '3',
            type: 'received',
            amount: 500.00000000,
            address: 'lmt1ghi...',
            time: 'Hace 3 días',
            status: 'confirmed'
        }
    ];
    
    updateTransactionsDisplay();
}

// Actualizar display de transacciones
function updateTransactionsDisplay() {
    elements.transactionsList.innerHTML = '';
    
    walletState.transactions.forEach(tx => {
        const txElement = createTransactionElement(tx);
        elements.transactionsList.appendChild(txElement);
    });
}

// Crear elemento de transacción
function createTransactionElement(tx) {
    const txDiv = document.createElement('div');
    txDiv.className = 'transaction-item';
    
    const iconClass = tx.type === 'received' ? 'fas fa-arrow-down received' : 'fas fa-arrow-up sent';
    const amountClass = tx.type === 'received' ? '' : 'sent';
    const amountPrefix = tx.type === 'received' ? '+' : '-';
    
    txDiv.innerHTML = `
        <div class="transaction-icon">
            <i class="${iconClass}"></i>
        </div>
        <div class="transaction-details">
            <div class="transaction-type">${tx.type === 'received' ? 'Recibido' : 'Enviado'}</div>
            <div class="transaction-amount ${amountClass}">${amountPrefix}${tx.amount.toFixed(8)} LMT</div>
            <div class="transaction-time">${tx.time}</div>
        </div>
        <div class="transaction-status ${tx.status}">
            <i class="fas fa-check-circle"></i>
        </div>
    `;
    
    return txDiv;
}

// Funciones de los modales
function showSendModal() {
    document.getElementById('sendModal').classList.add('show');
    document.body.style.overflow = 'hidden';
}

function closeSendModal() {
    document.getElementById('sendModal').classList.remove('show');
    document.body.style.overflow = 'auto';
}

function showReceiveModal() {
    document.getElementById('receiveModal').classList.add('show');
    document.body.style.overflow = 'hidden';
}

function closeReceiveModal() {
    document.getElementById('receiveModal').classList.remove('show');
    document.body.style.overflow = 'auto';
}

function closeAllModals() {
    closeSendModal();
    closeReceiveModal();
}

// Funciones de copiado
function copyAddress() {
    copyToClipboard(walletState.address, 'Dirección copiada al portapapeles');
}

function copyModalAddress() {
    copyToClipboard(walletState.address, 'Dirección copiada al portapapeles');
}

function copyToClipboard(text, message) {
    if (navigator.clipboard) {
        navigator.clipboard.writeText(text).then(() => {
            showNotification(message, 'success');
        }).catch(() => {
            fallbackCopyToClipboard(text, message);
        });
    } else {
        fallbackCopyToClipboard(text, message);
    }
}

function fallbackCopyToClipboard(text, message) {
    const textArea = document.createElement('textarea');
    textArea.value = text;
    textArea.style.position = 'fixed';
    textArea.style.left = '-999999px';
    textArea.style.top = '-999999px';
    document.body.appendChild(textArea);
    textArea.focus();
    textArea.select();
    
    try {
        document.execCommand('copy');
        showNotification(message, 'success');
    } catch (err) {
        showNotification('Error al copiar', 'error');
    }
    
    document.body.removeChild(textArea);
}

// Mostrar notificación
function showNotification(message, type = 'info') {
    const notification = document.createElement('div');
    notification.className = `notification ${type}`;
    notification.textContent = message;
    
    // Estilos de la notificación
    notification.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        padding: 1rem 1.5rem;
        border-radius: 8px;
        color: white;
        font-weight: 500;
        z-index: 10000;
        transform: translateX(100%);
        transition: transform 0.3s ease-out;
        max-width: 300px;
    `;
    
    // Colores según el tipo
    switch (type) {
        case 'success':
            notification.style.background = 'var(--success-color)';
            break;
        case 'error':
            notification.style.background = 'var(--error-color)';
            break;
        case 'warning':
            notification.style.background = 'var(--warning-color)';
            break;
        default:
            notification.style.background = 'var(--primary-color)';
    }
    
    document.body.appendChild(notification);
    
    // Animar entrada
    setTimeout(() => {
        notification.style.transform = 'translateX(0)';
    }, 100);
    
    // Auto-remover después de 3 segundos
    setTimeout(() => {
        notification.style.transform = 'translateX(100%)';
        setTimeout(() => {
            if (notification.parentNode) {
                notification.parentNode.removeChild(notification);
            }
        }, 300);
    }, 3000);
}

// Funciones de transacciones
function sendTransaction() {
    const recipientAddress = document.getElementById('recipientAddress').value;
    const amount = parseFloat(document.getElementById('amount').value);
    const fee = document.getElementById('fee').value;
    
    if (!recipientAddress || !amount || amount <= 0) {
        showNotification('Por favor completa todos los campos correctamente', 'error');
        return;
    }
    
    if (amount > walletState.balance.available) {
        showNotification('Saldo insuficiente', 'error');
        return;
    }
    
    // Simular envío de transacción
    showNotification('Transacción enviada correctamente', 'success');
    
    // Actualizar balance
    walletState.balance.available -= amount;
    walletState.balance.total -= amount;
    updateBalanceDisplay();
    
    // Agregar transacción a la lista
    const newTx = {
        id: Date.now().toString(),
        type: 'sent',
        amount: amount,
        address: recipientAddress.substring(0, 8) + '...',
        time: 'Ahora',
        status: 'pending'
    };
    
    walletState.transactions.unshift(newTx);
    updateTransactionsDisplay();
    
    // Cerrar modal
    closeSendModal();
    
    // Limpiar formulario
    document.getElementById('recipientAddress').value = '';
    document.getElementById('amount').value = '';
}

// Actualizar wallet
function refreshWallet() {
    showNotification('Actualizando wallet...', 'info');
    
    // Simular actualización
    setTimeout(() => {
        checkNodeConnection();
        loadWalletData();
        showNotification('Wallet actualizada', 'success');
    }, 1000);
}

// Ver todas las transacciones
function viewAllTransactions() {
    showNotification('Funcionalidad en desarrollo', 'info');
}

// Auto-refresh
function startAutoRefresh() {
    setInterval(() => {
        if (walletState.isConnected) {
            loadWalletData();
        }
    }, WALLET_CONFIG.refreshInterval);
}

// Funciones de utilidad
function formatNumber(num, decimals = 8) {
    return parseFloat(num).toFixed(decimals);
}

function formatAddress(address, start = 8, end = 4) {
    if (address.length <= start + end) return address;
    return address.substring(0, start) + '...' + address.substring(address.length - end);
}

// Exportar funciones para uso global
window.showSendModal = showSendModal;
window.closeSendModal = closeSendModal;
window.showReceiveModal = showReceiveModal;
window.closeReceiveModal = closeReceiveModal;
window.copyAddress = copyAddress;
window.copyModalAddress = copyModalAddress;
window.refreshWallet = refreshWallet;
window.viewAllTransactions = viewAllTransactions;
window.sendTransaction = sendTransaction;
