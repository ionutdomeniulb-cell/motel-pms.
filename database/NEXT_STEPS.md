# Inventar PMS și pasul tehnic următor

## Decizie de modelare
- `room_types`: tipuri comercializabile (ex. matrimonială, twin, triplă).
- `rooms`: camere fizice reale, cu număr și denumire unice.
- `bookings`: rezervare alocată unei camere fizice.
- `room_blocks`: indisponibilizări pentru mentenanță sau alte motive.
- `channels`: direct, telefon, WhatsApp, website, Booking.com etc.
- `channel_room_type_mappings`: pregătire pentru maparea tipurilor PMS la inventarul unui canal extern.
- `channel_sync_events`: jurnal de sincronizare pentru integrarea viitoare.
- `audit_log`: jurnal pentru modificări importante.

## Regula de disponibilitate
Datele se interpretează ca interval semi-deschis `[check_in, check_out)`.
Exemplu: sosire 10 octombrie, plecare 12 octombrie = două nopți; o altă rezervare poate începe pe 12 octombrie.

Schema PostgreSQL folosește o constrângere `EXCLUDE` GiST pentru a respinge suprapunerea intervalelor pe aceeași cameră, la nivelul bazei de date. Rezervările cu status `cancelled` nu blochează camera. Această protecție este mai puternică decât o verificare exclusiv în interfață.

Indisponibilizările din `room_blocks` au propria constrângere de suprapunere. Înainte de confirmarea unei rezervări, logica aplicației trebuie să verifice atât rezervările, cât și blocările de mentenanță, în aceeași tranzacție.

## Booking.com în viitor
În general, Booking.com vinde inventar pe tipuri de camere, nu neapărat numere fizice individuale. La primirea unei rezervări, integrarea trebuie:
1. să recunoască rezervarea externă idempotent, prin ID extern;
2. să identifice tipul de cameră mapat;
3. să aloce o cameră fizică disponibilă din acel tip;
4. să refuze alocarea dacă nu există disponibilitate și să ridice o alertă;
5. să actualizeze inventarul canalului prin conexiunea autorizată;
6. să înregistreze toate încercările și erorile de sincronizare.

Nu se presupune existența accesului API sau a unei conexiuni Booking.com. Acestea se verifică după înregistrarea proprietății și alegerea integrării.

## Următorul pas tehnic
1. Confirmați lista reală a celor 25 de camere: număr, denumire, tip, capacitate, etaj/dotări și dacă există camere ce trebuie excluse.
2. Migrați MVP-ul demonstrativ de la SQLite la PostgreSQL înainte de găzduirea multiutilizator.
3. Adăugați autentificare, roluri, protecție CSRF, audit, backup și HTTPS înainte de introducerea datelor reale.
4. Testați scenarii: două persoane rezervă aceeași cameră simultan; sosirea coincide cu plecarea; anulare; cameră în mentenanță; modificare a perioadei; rezervare externă duplicată.

## Atenționare
`postgres_schema.sql` este o schemă de pornire pentru dezvoltare, nu o migrare completă și testată a datelor SQLite. Trebuie revizuită și testată într-o bază de date nouă înainte de folosirea în producție.
