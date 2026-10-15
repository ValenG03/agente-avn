# agente-avn

Agente de Tráfico Web · AVN
App en Streamlit que lee el Google Analytics 4 de avnordelta.com y muestra:
Promedio de usuarios por día y la cantidad de usuarios de cada día (tabla + CSV)
Gráfico de línea de las visitas del último mes
Top 10 de secciones de más a menos visitada, con vistas y clics
Sección más visitada y sección con más potencial para crecer
Recomendaciones automáticas de qué cambiar y qué aprovechar
Mapa de calor del recorrido del mouse (vía Microsoft Clarity) y mapa de calor de tráfico por día y hora
Opcional: diagnóstico redactado por IA
Sin credenciales arranca en modo demo con números inventados (lo avisa con un cartel naranja).
Costo: todo lo obligatorio es gratis (Google Cloud, la API de GA4, Clarity y Streamlit Community Cloud). Lo único pago es el análisis con IA, que es opcional.
---
Paso 1 · Crear las credenciales de Google (gratis, ~10 min)
No hace falta cargar tarjeta: la API de Analytics no requiere facturación.
Entrá a https://console.cloud.google.com con tu cuenta de Google y creá un proyecto nuevo, por ejemplo `agente-avn`.
Andá a APIs y servicios → Biblioteca, buscá Google Analytics Data API y tocá Habilitar.
Andá a IAM y administración → Cuentas de servicio → Crear cuenta de servicio.
Nombre: `agente-avn`. No le asignes roles del proyecto (no los necesita). Terminá.
Entrá a la cuenta creada → pestaña Claves → Agregar clave → Crear clave nueva → JSON. Se descarga un archivo `.json`. Guardalo y no lo compartas ni lo subas a GitHub.
Copiá el mail de la cuenta de servicio (termina en `@agente-avn.iam.gserviceaccount.com` o similar).
Paso 2 · Darle acceso a la propiedad de GA4 de la AVN
Esto lo hace alguien con rol de Administrador en el Analytics de la AVN (vos, si te dieron ese permiso; si no, quien maneje la web).
En https://analytics.google.com, abrí la propiedad de avnordelta.com.
Administrar → Propiedad → Administración de acceso a la propiedad → + → Agregar usuarios.
Pegá el mail de la cuenta de servicio, rol Lector, y desmarcá "Notificar por correo".
En Administrar → Detalles de la propiedad, copiá el ID de la propiedad (solo números, por ejemplo `312345678`). No es el `G-XXXX`.
La cuenta de servicio solo puede leer reportes. No puede cambiar nada del Analytics ni de la web.
Paso 3 · Subir a GitHub y publicar en Streamlit
Creá un repositorio (puede ser privado) y subí: `app.py`, `requirements.txt`, `.gitignore`, `README.md` y la carpeta `.streamlit` con solo `secrets.toml.example`.
En https://share.streamlit.io → Create app → elegí el repo y `app.py`.
Antes de publicar, en Advanced settings → Secrets, pegá el contenido de `.streamlit/secrets.toml.example` con tus datos:
`GA4_PROPERTY_ID` = el número del paso 2.
En `[gcp_service_account]`, copiá cada campo del archivo JSON. El `private_key` va entre comillas y con los `\n` tal cual vienen en el JSON.
Deploy. Si las credenciales están bien, el cartel de "modo demo" desaparece y el punto de Google Analytics en la barra lateral se pone verde.
> **Ojo:** si el repo es público, la app también lo es. Cualquiera con el link vería el tráfico de la AVN. Para limitarlo, en Streamlit Cloud → Settings → Sharing, dejala visible solo para los mails que invites.
Para probarla en tu compu
```bash
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # y completalo
streamlit run app.py
```
Paso 4 · Mapa de calor del mouse con Microsoft Clarity (gratis)
Google Analytics no registra el movimiento del mouse. Clarity sí, y es gratis. La web de la AVN ya usa Google Tag Manager, así que se instala desde ahí sin tocar el código.
Creá un proyecto en https://clarity.microsoft.com con la URL `https://www.avnordelta.com`.
Instalación: elegí Google Tag Manager (Clarity te guía y crea la etiqueta), o en GTM creá una etiqueta HTML personalizado con el script que te da Clarity, activada en All Pages, y publicá el contenedor. Requiere acceso de edición al GTM de la AVN.
En Clarity, Settings → Setup → Google Analytics integration, vinculalo con GA4 (opcional, pero suma).
Para la app: Settings → Data Export → Generate new API token. Pegalo en los Secrets como `CLARITY_API_TOKEN`. El ID del proyecto (aparece en la URL de Clarity) va en `CLARITY_PROJECT_ID`.
Clarity empieza a grabar desde que se instala: no tiene datos hacia atrás. Con una o dos semanas de tráfico ya hay mapas útiles. Las imágenes de los mapas de calor se ven en Clarity (la app tiene un botón directo); la API exporta métricas como clics de frustración, clics muertos y profundidad de scroll, y permite pocas consultas por día, por eso la app las guarda 6 horas.
> Antes de instalar Clarity, consultá con la AVN si la política de privacidad del sitio necesita mencionar la grabación de sesiones. Clarity enmascara por defecto los textos que escribe el usuario.
Paso 5 (opcional) · Medir clics internos
Por defecto GA4 solo registra clics salientes (links a otros sitios), descargas de archivos y algunos formularios. Para contar clics en el menú y en botones internos, creá en GTM:
Activador: Clic - Solo enlaces, en todas las páginas.
Etiqueta: Evento de GA4 con nombre `click_interno` y parámetro `link_text = {{Click Text}}`.
La app ya incluye `click_interno` en los eventos que cuenta como clic.
Paso 6 (opcional) · Análisis con IA
Agregá `ANTHROPIC_API_KEY` en los Secrets (se crea en https://console.anthropic.com). Es pago por uso; cada análisis cuesta unos centavos de dólar. Sin esta clave, las recomendaciones de la pestaña Oportunidades igual funcionan con reglas.
---
Cómo leer los números
Usuarios = "Usuarios activos" de GA4, el mismo número que muestra el panel de Analytics. GA4 calcula los usuarios únicos con un método estadístico, así que puede haber diferencias mínimas con otras herramientas.
El período es de los últimos 30 días completos (hasta ayer), comparado con los 30 días anteriores.
Índice de potencial (0–100): combina tiempo de lectura por vista (40%), poco tráfico actual (25%), crecimiento contra el mes anterior (20%) y bajo rebote (15%).
Los datos se guardan una hora en caché para no gastar la cuota diaria de la API. El botón Actualizar datos fuerza una nueva consulta.
Problemas comunes
Error	Solución
`403 PERMISSION_DENIED`	La cuenta de servicio no fue agregada como Lector en la propiedad (paso 2) o el ID de propiedad es otro.
`API has not been used in project`	Falta habilitar Google Analytics Data API (paso 1.2).
`Could not deserialize key data`	El `private_key` se pegó mal en los Secrets. Copialo entero, con comillas y los `\n`.
La app sigue en modo demo	Falta `GA4_PROPERTY_ID` o la sección `[gcp_service_account]` en los Secrets.
Clics en 0	Falta configurar la medición de clics (paso 5).
