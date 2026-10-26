# Integrare cu Home Assistant — contract PMS (v1)

Principiu: **PMS-ul spune în ce stare e fiecare cameră; Home Assistant decide ce face cu asta.**
PMS-ul nu comandă niciun dispozitiv, iar o cădere a unuia dintre sisteme nu o blochează pe cealaltă.

## Activare
API-ul este **dezactivat implicit**. Se activează cu un token (minimum 24 de caractere, generat de dumneavoastră):

```powershell
$env:MOTEL_API_TOKEN = "un-token-lung-si-aleatoriu"
$env:MOTEL_SECRET_KEY = "o-cheie-secreta-proprie"
$env:MOTEL_HOST = "0.0.0.0"      # doar dacă Home Assistant rulează pe alt dispozitiv din rețea
py app.py
```
Fără `MOTEL_SECRET_KEY` propriu, aplicația refuză să pornească în rețea. Folosiți API-ul doar în rețeaua locală, nu pe internet.
Antet obligatoriu: `Authorization: Bearer <token>`. API-ul este doar pentru citire (plus confirmarea evenimentelor).

## Stări de cameră (`state`)
| Valoare | Semnificație |
|---|---|
| `vacant_clean` | liberă, marcată curată azi de cameriste |
| `vacant_to_check` | liberă, încă nemarcată curată azi |
| `arriving` | sosire astăzi, clientul nu a sosit încă |
| `occupied` | în sejur (cazat sau cu sejur în desfășurare) |
| `departing` | plecare astăzi, check-out nefinalizat |
| `out_of_order` | marcată defectă |

Câmpuri utile pentru scenarii: `arrival_today`, `departure_today`, `occupied_tonight`, `next_arrival_date`, `clean_today`.
Numele clienților și notele de mentenanță **nu** sunt expuse prin API.

## Endpoint-uri
- `GET /api/v1/health`
- `GET /api/v1/rooms` — starea tuturor camerelor (sursa de adevăr; interogați-l periodic, ex. la 30–60 s)
- `GET /api/v1/rooms/camera_101` — o singură cameră
- `GET /api/v1/events?after_id=0&limit=100` — evenimente noi, pentru reacție rapidă
- `POST /api/v1/events/ack` cu JSON `{"up_to_id": 123}` — marchează evenimentele ca preluate

Evenimente: `booking_created`, `booking_updated`, `booking_cancelled`, `booking_reconfirmed`, `booking_unconfirmed`,
`room_clean_changed`, `room_maintenance_changed`, `housekeeping_request_created`, `housekeeping_request_done`.
Fiecare conține starea camerei imediat după schimbare. Evenimentele se păstrează în baza de date, deci nu se pierd
dacă Home Assistant este oprit; la repornire cereți `after_id=<ultimul id procesat>`.

Atenție: unele schimbări de stare apar doar cu trecerea timpului (ex. la miezul nopții o sosire devine ocupare),
fără eveniment. De aceea `GET /api/v1/rooms` rămâne sursa de adevăr, iar evenimentele sunt doar accelerator.

## Exemplu de pornire în Home Assistant (de testat la pasul de integrare)
```yaml
rest:
  - resource: http://ADRESA_NUC:5000/api/v1/rooms
    scan_interval: 30
    headers:
      Authorization: "Bearer TOKENUL_DUMNEAVOASTRA"
    sensor:
      - name: "PMS camera 101"
        unique_id: pms_camera_101
        value_template: "{{ (value_json.rooms | selectattr('room_code','equalto','camera_101') | first).state }}"
```
