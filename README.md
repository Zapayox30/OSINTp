# OSINTp 🔎

**Framework modular de OSINT (Open Source Intelligence) construido con FastAPI.**

OSINTp recopila inteligencia de fuentes **públicas y sin autenticación**, exponiéndola
a través de una API REST limpia, asíncrona y documentada automáticamente (OpenAPI/Swagger).

> ⚠️ **Uso responsable.** Esta herramienta consulta únicamente información pública.
> Úsala de forma legal y ética: investigación de seguridad defensiva, pentesting
> autorizado, threat intelligence, periodismo o fines educativos. No la uses para
> acosar, perfilar sin consentimiento ni violar términos de servicio o leyes locales.

---

## ✨ Módulos

| Módulo | Endpoint | Qué hace | Fuentes |
|--------|----------|----------|---------|
| **Username** | `/api/v1/username` | Busca un handle en ~30 plataformas en paralelo | Páginas/APIs públicas |
| **Email** | `/api/v1/email` | Validación de sintaxis, registros MX, Gravatar, brechas (opcional) | DNS, Gravatar, HIBP* |
| **Domain** | `/api/v1/domain` | Registros DNS, WHOIS, certificado TLS, subdominios | DNS, WHOIS, crt.sh |
| **IP** | `/api/v1/ip` | Geolocalización, ASN, DNS inverso | ip-api.com, ipinfo* |
| **Investigate** | `/api/v1/investigate` | Autodetecta el tipo de objetivo y agrega los módulos | — |

\* Requiere una API key opcional (`HIBP_API_KEY`, `IPINFO_TOKEN`). Si no se configura,
el módulo se omite limpiamente (`status: skipped`).

---

## 🏗️ Arquitectura

Separación de responsabilidades en capas, fácil de extender y testear:

```
app/
├── main.py                  # App factory + lifespan (arranca/cierra el cliente HTTP)
├── core/                    # Infraestructura transversal
│   ├── config.py            #   Settings (pydantic-settings, .env)
│   ├── logging.py           #   Logging estructurado
│   ├── http_client.py       #   Cliente httpx.AsyncClient compartido (pooling)
│   └── concurrency.py       #   gather_bounded() — fan-out con límite de workers
├── schemas/                 # Modelos Pydantic (contrato de la API)
│   ├── common.py            #   SourceResult, ResultEnvelope, SourceStatus
│   └── username|email|domain|ip|investigation.py
├── services/                # Lógica OSINT (una clase por dominio)
│   ├── username_service.py
│   ├── email_service.py
│   ├── domain_service.py
│   └── ip_service.py
├── modules/                 # Datos/colectores declarativos
│   └── username/
│       ├── sites.json       #   Registro de sitios (editable)
│       └── registry.py      #   Carga y valida el registro
└── api/                     # Capa HTTP
    ├── deps.py              #   Inyección de dependencias (servicios)
    ├── router.py            #   Router raíz (/api/v1/...)
    └── v1/endpoints/        #   username, email, domain, ip, investigation
```

**Principios de diseño**

- **Asíncrono de extremo a extremo** — un único `httpx.AsyncClient` con pool de
  conexiones, reutilizado vía el `lifespan` de FastAPI.
- **Fan-out controlado** — las sondas concurrentes se limitan con un `Semaphore`
  (`MAX_CONCURRENCY`) para no saturar la red ni las fuentes.
- **Respuestas normalizadas** — todo módulo devuelve un `ResultEnvelope` con una
  lista de `SourceResult` homogéneos (`found` / `not_found` / `error` / `rate_limited` / `skipped`).
- **Degradación elegante** — un error en una fuente nunca tumba la consulta completa.

---

## 🚀 Inicio rápido

### Opción A — Local (Python ≥ 3.10)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # opcional: ajusta variables / API keys

uvicorn app.main:app --reload
```

Abre la documentación interactiva en **http://localhost:8000/docs**.

### Opción B — Docker

```bash
cp .env.example .env
docker compose up --build
```

---

## 📡 Ejemplos de uso

```bash
# Buscar un username en todas las plataformas
curl "http://localhost:8000/api/v1/username?username=torvalds"

# Restringir por categorías
curl "http://localhost:8000/api/v1/username?username=torvalds&categories=dev&categories=social"

# Inteligencia de email
curl "http://localhost:8000/api/v1/email?email=torvalds@linux-foundation.org"

# Inteligencia de dominio (DNS + WHOIS + TLS + subdominios)
curl "http://localhost:8000/api/v1/domain?domain=example.com"

# Inteligencia de IP (geo + ASN + DNS inverso)
curl "http://localhost:8000/api/v1/ip?ip=8.8.8.8"

# Investigación con autodetección del tipo de objetivo
curl -X POST "http://localhost:8000/api/v1/investigate" \
     -H "Content-Type: application/json" \
     -d '{"target": "example.com"}'
```

Ejemplo de respuesta (recortada) de `/api/v1/username`:

```json
{
  "target": "torvalds",
  "module": "username",
  "summary": { "sites_checked": 29, "found_count": 3, "found_on": ["GitHub", "Keybase", "Reddit"] },
  "results": [
    { "source": "GitHub", "category": "dev", "status": "found", "url": "https://github.com/torvalds", "elapsed_ms": 142.0 }
  ]
}
```

---

## ⚙️ Configuración

Todas las variables son opcionales (ver `.env.example`):

| Variable | Por defecto | Descripción |
|----------|-------------|-------------|
| `DEBUG` | `false` | Logging detallado |
| `HTTP_TIMEOUT` | `10.0` | Timeout por petición (s) |
| `MAX_CONCURRENCY` | `20` | Sondas concurrentes por petición |
| `CORS_ORIGINS` | `*` | Orígenes permitidos (CSV) |
| `IPINFO_TOKEN` | — | Enriquece el módulo IP |
| `HIBP_API_KEY` | — | Habilita búsqueda de brechas en el módulo Email |

---

## 🧩 Extender el framework

**Añadir un sitio al buscador de usernames** — edita `app/modules/username/sites.json`:

```json
{ "name": "Trello", "category": "social", "url": "https://trello.com/{}", "check": "status" }
```

Detección por estado HTTP (`status`) o por mensaje en el cuerpo (`message`, usando
`found_messages` o `error_messages`). Sin tocar una sola línea de Python.

**Añadir un módulo nuevo** — crea un servicio en `app/services/`, su esquema en
`app/schemas/`, un router en `app/api/v1/endpoints/` y regístralo en `app/api/router.py`.

---

## 🧪 Tests

```bash
pytest -q
```

La suite no realiza llamadas de red: valida el registro de sitios, la validación de
entradas, la autodetección de objetivos y los endpoints meta.

---

## 📋 Notas sobre fiabilidad de las fuentes

Algunas plataformas emplean protección anti-bot, CDNs o renderizado por JavaScript
y pueden devolver resultados ambiguos (`error`) según la red de origen. El registro
de sitios prioriza endpoints estables (APIs JSON donde es posible: Docker Hub, Reddit,
Chess.com). Trátalo como **señal, no como prueba**: confirma siempre manualmente.

---

## 📄 Licencia

MIT.
