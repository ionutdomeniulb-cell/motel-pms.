# Cum testați alertele recepție ↔ cameriste

## Pregătire (5 minute)
1. Porniți aplicația: `py app.py`, apoi deschideți `http://127.0.0.1:5000`.
2. În **Utilizatori** creați un cont cu rol „Cameristă" (ex. `maria`, PIN 6–8 cifre).
3. Deschideți **două ferestre/dispozitive**: recepția (admin) într-o fereastră normală, camerista într-o fereastră privată sau pe telefon.
   Pe telefon, în aceeași rețea, porniți cu `$env:MOTEL_HOST="0.0.0.0"` și `$env:MOTEL_SECRET_KEY="o-cheie-proprie"`.
4. **În ambele ferestre atingeți pagina o dată.** Browserele permit sunetul numai după o atingere.
   Butonul din colțul dreapta-jos arată „🔔 Alerte active"; dacă arată „🔇 Atingeți pentru sunet", atingeți din nou.

## Test rapid, fără date reale
Apăsați butonul din colțul dreapta-jos → **Testează alerta urgentă** / **Testează alerta de informare**.
Verificați că auziți sunetul și vedeți bannerul. Alertele de probă nu se salvează.

## Scenarii reale
| Acțiune | Cine o face | Cine primește alerta | Tip |
|---|---|---|---|
| Recepția apasă „＋ Solicită serviciu" | recepție | cameristă | **urgentă**: banner galben care rămâne, sunet repetat la 20 s (maximum 6 ori), titlul filei clipește, vibrație pe telefon |
| Cameristă „Marchează rezolvată" | cameristă | recepție | informare: banner 20 s, sunet scurt |
| Cameristă „Marchează curată" / debifează | cameristă | recepție | informare |
| Recepția finalizează check-out (status „Plecat") | recepție | cameristă | informare: „Cameră eliberată" |
| Cameră marcată defectă / revenită în service | recepție | cameristă | informare |
| Trece ora de check-out (13:00) fără check-out finalizat | automat | cameristă și recepție | informare: Cameră eliberată automat / Check-out neconfirmat |
| Cameristă trimite formularul de curățenie extinsă | cameristă | recepție | informare, cu observațiile |

Persoana care face acțiunea nu primește alertă pentru propria acțiune.
Alerta urgentă rămâne pe ecran până la „Am văzut" sau până când solicitarea este rezolvată, chiar dacă schimbați pagina.

## Ce să verificați
- Alerta ajunge în maximum ~5 secunde.
- Pagina se actualizează singură, fără reîncărcare (nu se pierde ce ați scris într-un formular deschis).
- Panoul „Solicitări și stare camere" din recepție arată doar solicitările în desfășurare; „Istoric de azi și stare camere" se extinde la cerere și își păstrează starea.
- „Activează notificările din browser" (în panoul de lângă clopoțel) afișează alerte și când fila nu este activă.

## Limite de știut
- Browserele restricționează sunetul în fila ascunsă sau pe ecran blocat; pentru asta există titlul care clipește și notificările din browser.
  Pentru o tabletă dedicată cameristelor, lăsați pagina deschisă, cu ecranul pornit.
- Evenimentele mai vechi de 30 de minute nu mai generează alerte la reconectare.

## Test rapid al trecerii automate de la 13:00
Porniți aplicația cu ora de check-out peste 2 minute (la 12:30 scrieți `$env:MOTEL_CHECKOUT_TIME="12:32"`).
O cameră cu plecare azi (status Cazat, plecare astăzi) apare „Plecare azi", iar după 12:32 devine „Liberă · auto", cu alertă în ~30–40 s.

## Telefon
Vezi `MOBIL.md` (acces din rețea, sunet pe Android/iOS, HTTPS, pictogramă pe ecran).
