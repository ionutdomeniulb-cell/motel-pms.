# Securitate — V17

Aplicația rulează local (NUC, rețea Wi-Fi a motelului). Măsurile de mai jos urmează OWASP Top 10 (2021) și OWASP ASVS nivel 1,
adaptate unei aplicații interne mici.

## Măsuri aplicate
| Risc (OWASP 2021) | Măsură |
|---|---|
| A01 Control acces | Refuz implicit: orice rută în afara `/login` și `/setup` cere autentificare. Roluri separate (administrator, recepție, cameristă, șef de tură, recepție noapte), fiecare limitat la paginile sale; rutele de administrare marcate și verificate automat. `/setup` se închide după primul cont. |
| A01 CSRF | Token CSRF obligatoriu pe toate formularele POST (verificat automat pe fiecare rută). Cookie `SameSite=Lax`. |
| A02 Criptografie | PIN-uri stocate doar ca hash (Werkzeug). Cheie de sesiune aleatorie de 256 biți, persistată în `secret.key` (0600); cheile din mediu sub 32 de caractere sunt ignorate. Cu HTTPS: cookie `Secure` + HSTS. |
| A03 Injecții | Toate interogările SQL sunt parametrizate. Șabloanele escapează automat (fără `|safe`). Notificările se afișează cu `textContent`. Exporturile CSV/Excel neutralizează formulele (`=`, `+`, `-`, `@`). |
| A04 Proiectare | Recepția de noapte nu poate modifica o cameră cazată; anulările de grup cer confirmare explicită; operațiunile pe camere folosesc tranzacții `BEGIN IMMEDIATE` (fără dublă cazare). |
| A05 Configurare | Content-Security-Policy strictă cu nonce (fără scripturi/handlere inline), `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy`, `Permissions-Policy`, COOP/CORP, `Cache-Control: no-store` pentru pagini, antet `Server` neutru, pagini de eroare fără detalii tehnice, limită de 256 KB pe cerere, depanare dezactivată. |
| A07 Autentificare (V17) | Autentificare în 2 pași obligatorie pentru administratori (TOTP RFC 6238, 6 cifre/30 s; cheia rămâne pe server; coduri de rezervă stocate doar ca hash; blocare 15 min după 5 coduri greșite; un cod nu poate fi folosit de două ori; pasul 2 expiră în 5 minute). Sesiunile unui utilizator se închid pe toate dispozitivele la schimbarea rolului/PIN-ului, la dezactivare sau la cerere. Resetare de urgență doar din consola PC-ului (`manage.py reset-2fa`). |
| A07 Autentificare | Blocare 15 min după 5 eșecuri pe IP sau 10 pe utilizator; timp de răspuns egalizat (nu se poate afla dacă un utilizator există); mesaj de eroare unic; PIN 6–8 cifre, fără serii simple la conturi noi; expirare la inactivitate (administrator 30 min, personal 12 h; interogările automate nu prelungesc sesiunea); sesiune valabilă doar în ziua autentificării; protecție open-redirect. |
| A08 Integritate | Fără încărcări de fișiere, fără deserializare. Jurnal de audit pentru acțiunile importante. |
| A09 Jurnalizare | Audit în baza de date și fișier; accesele refuzate (403) se jurnalizează. |
| API | Token obligatoriu (minimum 24 de caractere), comparație în timp constant, limitare la 10 încercări greșite / 15 min, doar citire, fără date personale. |
| Date | Validare cu limite (nume, telefon, e-mail, tarif 0–10.000 lei inclusiv respingerea NaN/infinit, avans, ședere max. 90 nopți). Baza de date cu permisiuni private. Recepția de noapte vede nume/telefon doar pentru sosirile târzii; șeful de tură nu vede nume. |

## Disponibilitate (V17)
- Copii automate zilnice ale bazei (API-ul de backup SQLite, verificate cu `integrity_check`, rotație după numărul de zile setat); copiile nu sunt accesibile prin web.
- Server de producție `cheroot` (cu HTTPS); serverul de dezvoltare doar ca rezervă, cu avertisment.
- Ceasul de test se activează doar explicit, din mediu, și afișează o bandă roșie pe toate paginile.

## Cum a fost verificat
- 140 de teste automate (`py -m unittest discover -s tests`), dintre care o suită dedicată securității:
  - toate rutele (autentificare implicită, token API);
  - acces între roluri;
  - CSRF pe fiecare POST;
  - antete;
  - lipsa scripturilor inline;
  - cookie-uri și cheie secretă;
  - expirare sesiune;
  - blocări la autentificare;
  - open redirect;
  - politică de PIN;
  - injecții SQL;
  - XSS stocat pe toate paginile;
  - metode HTTP, parcurgere de cale, fișiere sensibile, limită de mărime;
  - pagini de eroare;
  - formule în exporturi;
  - limite de validare.
- Test în browser real, pentru toate rolurile, fără nicio încălcare CSP și fără erori JavaScript.
- Scanare statică (căutare de funcții periculoase, SQL construit dinamic, secrete în clar, `|safe`): fără probleme.
- Versiuni testate: Flask 3.1.3, Werkzeug 3.1.7, Jinja2 3.1.6, openpyxl 3.1.5, Python 3.12.

## Limite (ce NU acoperă această verificare)
- Nu s-au putut rula scanere externe (pip-audit, bandit, OWASP ZAP) — mediul de dezvoltare nu are acces la internet.
  Recomandat, pe NUC: `pip install pip-audit bandit` apoi `pip-audit -r requirements.txt` și `bandit -r . -x tests`.
- Nu este un test de penetrare realizat de o terță parte.
- Serverul integrat Flask este potrivit pentru rețeaua locală a motelului, nu pentru expunere pe internet.

## Recomandări de exploatare
1. **Nu expuneți aplicația pe internet** (fără port forwarding). Pentru acces din afară: VPN (ex. WireGuard/Tailscale).
2. **HTTPS în rețeaua locală** (vezi MOBIL.md): activează cookie `Secure`, HSTS și funcțiile telefonului.
3. Rețea Wi-Fi separată pentru clienți (guest), diferită de cea a personalului și a NUC-ului.
4. Firewall Windows: portul 5000 doar pe profilul „Privat”.
5. Actualizări Windows și Python; rulați `pip-audit` lunar.
6. Copii de siguranță zilnice ale `motel.db` pe un suport separat; `secret.key` nu se trimite nimănui.
7. Fiecare angajat cu cont propriu; dezactivați imediat conturile celor care pleacă.
8. GDPR: datele clienților (nume, telefon, e-mail) se folosesc doar pentru cazare; stabiliți o perioadă de păstrare și informați
   personalul despre pontaj.
