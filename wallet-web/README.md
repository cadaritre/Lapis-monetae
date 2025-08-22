# 🪙 Lapis Monetae Wallet Web

Una interfaz web moderna y elegante para la wallet de Lapis Monetae (LMT) que se ejecuta localmente.

## ✨ Características

- 🎨 **Diseño moderno** con gradientes y animaciones
- 📱 **Responsive** para todos los dispositivos
- 🔗 **Conexión en tiempo real** con el nodo LMT
- 💰 **Gestión de balance** y transacciones
- 📤 **Envío y recepción** de LMT
- 🔄 **Auto-actualización** cada 10 segundos
- 📋 **Historial de transacciones** con estados
- 🎯 **Modales interactivos** para operaciones

## 🚀 Instalación y Uso

### **1. Requisitos previos**
- Navegador web moderno (Chrome, Firefox, Safari, Edge)
- Nodo Lapis Monetae ejecutándose (opcional para funcionalidad completa)

### **2. Ejecutar la wallet**

#### **Opción A: Abrir directamente en el navegador**
```bash
# Navegar a la carpeta
cd wallet-web

# Abrir el archivo HTML en tu navegador
# Doble clic en index.html o arrastrar al navegador
```

#### **Opción B: Servidor local simple**
```bash
# Con Python 3
python -m http.server 8080

# Con Node.js
npx http-server -p 8080

# Con PHP
php -S localhost:8080
```

Luego abrir: `http://localhost:8080`

### **3. Configurar conexión al nodo**

Si tienes un nodo LMT ejecutándose, edita `script.js` y cambia:

```javascript
const WALLET_CONFIG = {
    rpcUrl: 'http://localhost:16111', // Tu puerto RPC
    // ... resto de configuración
};
```

## 🎯 Funcionalidades

### **Dashboard Principal**
- **Balance total** con visualización destacada
- **Balance disponible** y en transacciones
- **Estado de conexión** al nodo
- **Acciones rápidas** (Enviar, Recibir, Actualizar)

### **Gestión de Direcciones**
- **Dirección de recepción** con copiado rápido
- **Código QR** (placeholder para implementación futura)
- **Formato legible** de direcciones LMT

### **Transacciones**
- **Historial completo** de transacciones
- **Estados** (Confirmado, Pendiente)
- **Tipos** (Recibido, Enviado)
- **Montos** y timestamps

### **Operaciones**
- **Enviar LMT** con validación de saldo
- **Selección de tarifas** (Baja, Media, Alta)
- **Validación de direcciones** de destino
- **Confirmaciones** en tiempo real

## 🔧 Configuración

### **Personalizar colores**
Edita `styles.css` y modifica las variables CSS:

```css
:root {
    --primary-color: #6366f1;      /* Color principal */
    --secondary-color: #8b5cf6;    /* Color secundario */
    --background: #0f172a;         /* Fondo principal */
    --surface: #1e293b;            /* Superficies */
}
```

### **Cambiar puerto RPC**
En `script.js`:

```javascript
const WALLET_CONFIG = {
    rpcUrl: 'http://localhost:TU_PUERTO',
    // ... resto de configuración
};
```

### **Intervalo de actualización**
```javascript
const WALLET_CONFIG = {
    refreshInterval: 5000, // 5 segundos
    // ... resto de configuración
};
```

## 📱 Responsive Design

La wallet se adapta automáticamente a:

- **Desktop** (1200px+): Layout completo con sidebar
- **Tablet** (768px-1199px): Layout adaptado
- **Mobile** (<768px): Layout vertical optimizado

## 🎨 Temas y Personalización

### **Tema Oscuro (por defecto)**
- Fondo oscuro con gradientes
- Colores vibrantes para elementos importantes
- Alto contraste para mejor legibilidad

### **Personalización de fuentes**
```css
body {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
}
```

## 🔒 Seguridad

- **No almacena claves privadas** (solo interfaz)
- **Conexión local** por defecto
- **Validación de entrada** en formularios
- **Sanitización** de datos de usuario

## 🚧 Funcionalidades Futuras

- [ ] **Generación de códigos QR** reales
- [ ] **Múltiples wallets** en una sesión
- [ ] **Exportar historial** a CSV/PDF
- [ ] **Notificaciones push** del navegador
- [ ] **Tema claro** alternativo
- [ ] **Múltiples idiomas**
- [ ] **Integración con hardware wallets**

## 🐛 Solución de Problemas

### **La wallet no se conecta al nodo**
1. Verifica que el nodo esté ejecutándose
2. Confirma el puerto RPC en la configuración
3. Revisa el firewall y permisos de red

### **Los estilos no se cargan**
1. Verifica que `styles.css` esté en la misma carpeta
2. Limpia la caché del navegador
3. Revisa la consola del navegador para errores

### **Las transacciones no se actualizan**
1. Verifica la conexión al nodo
2. Confirma el intervalo de actualización
3. Revisa la consola para errores de red

## 📚 API del Nodo

La wallet se conecta a la API RPC del nodo LMT:

- **Endpoint**: `http://localhost:16111`
- **Método**: POST
- **Formato**: JSON-RPC 2.0

### **Métodos utilizados**
- `getNetworkStatus` - Estado de la red
- `getBalance` - Balance de la wallet
- `getTransactions` - Historial de transacciones
- `sendTransaction` - Enviar transacción

## 🤝 Contribuir

1. **Fork** del repositorio
2. **Crea** una rama para tu feature
3. **Commit** tus cambios
4. **Push** a la rama
5. **Abre** un Pull Request

## 📄 Licencia

Este proyecto está bajo la licencia MIT. Ver `LICENSE` para más detalles.

## 🆘 Soporte

- **Issues**: Reporta bugs en GitHub
- **Discussions**: Preguntas y sugerencias
- **Wiki**: Documentación adicional

---

**Desarrollado con ❤️ para la comunidad Lapis Monetae**
