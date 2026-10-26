# V17 — setări pe module, autentificare în 2 pași, copii automate

Actualizare: `V17_UPDATE_INSTRUCTIONS.txt`. Pornire: `porneste.ps1` (vezi ghidul de instalare). Recepția de noapte: `NOAPTE.md`. Securitate: `SECURITY.md`. Telefon: `MOBIL.md`.

---

# Actualizare V12 de la V11 — păstrarea datelor

**Nu copiați V12 peste folderul V11 și nu porniți aplicația V12 înainte să puneți baza de date V11 în folderul nou.** Arhiva V12 nu include `motel.db`, tocmai pentru a evita înlocuirea accidentală a datelor existente.

1. Opriți aplicația V11 și faceți o copie de siguranță a întregului folder, în special a fișierului `motel.db`.
2. Dezarhivați V12 într-un folder nou.
3. Copiați baza de date `motel.db` din folderul V11 în folderul nou V12. Dacă există fișierele `motel.db-wal` sau `motel.db-shm`, copiați-le numai după oprirea aplicației, împreună cu baza de date.
4. În folderul V12, instalați dependențele cu `pip install -r requirements.txt` și porniți aplicația. La prima pornire, V12 face migrarea schemei și încearcă să creeze o copie de siguranță înainte de migrare în `backups`.
5. Testați pe o copie a bazei de date înainte de a folosi aplicația în activitatea curentă.

Dacă V12 este pornită fără `motel.db`, va crea o bază de date nouă, fără rezervările V11. Nu folosiți această bază goală în locul bazei reale.

---

# Popas Căprioara PMS — v10 Test

Această versiune extinde prototipul local pentru calendarul de rezervări al celor 25 de camere.

## Noutăți în această versiune

- Autentificare individuală cu PIN de 6–8 cifre; PIN-urile sunt stocate ca hash.
- Roluri `admin` și `reception`; administratorul gestionează conturile și vede jurnalul de audit.
- Limitare temporară după 5 încercări nereușite de autentificare într-un interval de 15 minute (pe IP).
- Token CSRF pentru formularele POST.
- Jurnal de audit pentru autentificări reușite/eșuate, rezervări, utilizatori, accesarea rapoartelor și testele de facturare; evenimentele se salvează în SQLite și în `logs/audit.log` (UTF-8 JSON Lines).
- Export TXT al jurnalului de audit, ușor de deschis cu Notepad.
- Apăsarea unei celule din calendar deschide o rezervare nouă cu camera și check-in-ul precompletate; revenirea la calendar sau salvarea păstrează data selectată în vizualizare.
- Culoare distinctă per utilizator pentru rezervările noi; numele și culoarea creatorului sunt păstrate în rezervare chiar dacă acel cont este șters ulterior.
- Ștergerea conturilor este disponibilă administratorului, cu protecție împotriva ștergerii propriului cont sau a ultimului administrator.
- Rapoarte doar pentru administrator: camere cu cel puțin o noapte vândută, nopți vândute, grad de ocupare, venit estimat și defalcare pe corp/cameră pentru o perioadă selectată.
- Tabele pentru facturi și încercări de emitere, cu cheie de idempotentă și o singură înregistrare de factură de test per rezervare.
- Copie de siguranță automată a bazei de date înainte de prima migrare a schemei.
- Păstrează inventarul și rezervările existente din baza de date inclusă.

## Pornire pe Windows

1. **Păstrează arhiva veche și nu o extrage peste folderul vechi.** Extrage această arhivă într-un folder nou.
2. Instalează Python 3.11 sau mai nou.
3. Deschide PowerShell în folderul `motel_pms_mvp`.
4. Rulează:

   ```powershell
   py -m venv .venv
   .venv\\Scripts\\activate
   pip install -r requirements.txt
   py app.py
   ```

5. Deschide `http://127.0.0.1:5000`.
6. La prima pornire, creează contul administratorului și un PIN de 6–8 cifre. **Nu există un PIN implicit.**
7. Din meniul „Utilizatori”, creează câte un cont individual pentru fiecare angajat de la recepție.

Aplicația pornește pe `127.0.0.1`, deci este accesibilă doar de pe calculatorul local. Nu o publica direct pe internet.

## Baza de date și actualizări

- Baza de date este `motel.db`.
- La actualizarea schemei la versiunea 5, aplicația creează automat un snapshot în folderul `backups` înainte să adauge coloanele pentru creatorul rezervării.
- Înainte de orice actualizare, oprește aplicația și copiază separat fișierul `motel.db` într-o locație sigură.
- Pentru testare, pornește versiunea nouă într-un folder separat. Nu șterge folderul și baza veche până când verifici calendarul și rezervările.
- Copia automată este o măsură suplimentară, nu înlocuiește backupul separat și testarea restaurării.

## Testarea Oblio — atenție

Butonul „Testează emiterea facturii” este **o simulare locală**. Nu se conectează la Oblio, nu transmite date în afara calculatorului și nu emite o factură fiscală reală. Înregistrează o operațiune de test, totalul calculat și încercările ulterioare blocate ca duplicate. Integrarea reală cu API-ul Oblio trebuie configurată și testată separat înainte de a permite emiterea documentelor fiscale.

Documentația oficială Oblio: https://www.oblio.eu/api/

## Teste automate

Din folderul proiectului:

```powershell
python -m unittest discover -s tests -v
```

Testele automate acoperă inventarul, calendarul clickabil, precompletarea camerei/datei, validarea capacității, suprapunerile, ziua de check-out, protecția anti-duplicat, creatorul rezervării, rapoartele, exportul de audit și ștergerea utilizatorilor.


### V12 — coordonare recepție și cameriste
- Modulul cameristelor afișează doar ziua curentă, camerele pe corpuri și starea clară: ocupată, plecare astăzi, curată sau de verificat. O cameră ocupată nu poate fi bifată ca pregătită pentru o nouă cazare.
- Recepția poate crea o solicitare pentru curățenie, schimb prosoape sau ambele, cu notă opțională. Solicitările apar în ambele interfețe, au status deschis/rezolvat și păstrează cine a solicitat și cine a rezolvat. O solicitare rezolvată nu marchează automat camera ca fiind curată.
- Administratorul poate crea utilizatori cu profil Cameristă. Aceștia văd doar modulul de housekeeping și pot marca starea camerelor și rezolva solicitările.
- Exportul rapoartelor este XLSX real, cu cinci foi normalizate, formule pentru gradul de ocupare, filtre, tabele și grafice pentru ocuparea pe corpuri și pe zile. Capacitatea și nopțile vândute exclud camerele marcate defecte; venitul estimat rămâne evidențiat separat.

## Limitări și securitate

Aceasta este în continuare o versiune locală de test, nu o versiune de producție. Înainte de folosirea cu date reale sau acces online sunt necesare, între altele: HTTPS, cheie secretă de mediu puternică, server WSGI de producție, backup automat extern și restaurare testată, revizuire de securitate, politici GDPR, gestionarea schimbării PIN-ului, expirarea/scoaterea sesiunilor, migrare testată la PostgreSQL și protecția anti-suprapunere la nivel de bază de date.

Pentru instalarea locală, `MOTEL_SECRET_KEY` poate fi setată ca variabilă de mediu. Nu utiliza valoarea implicită de dezvoltare într-un mediu accesibil altor calculatoare.


## v5 — funcții noi pentru testare

### Raport Excel
În secțiunea „Rapoarte”, alegeți perioada și folosiți „Descarcă raport Excel (.xlsx) cu grafice” sau „Descarcă CSV pentru Excel”. Raportul conține rezumatul, comparația pe corpuri și detaliul pe camere. Dacă generarea XLSX întâmpină o eroare de bibliotecă/format, aplicația livrează un CSV compatibil cu Excel în locul erorii 500. Butonul „Afișează statisticile” păstrează vizualizarea din aplicație.

### Tarif obligatoriu
Tariful pe noapte trebuie completat și să fie mai mare decât 0. Validarea se face atât în formular, cât și pe server. Rezervările vechi care au fost importate cu tarif 0 trebuie corectate înainte ca venitul estimat să fie relevant.

### Rezervări de grup
Folosiți „Rezervare grup” din bara de navigare, selectați mai multe camere și perioada. Aplicația verifică disponibilitatea tuturor camerelor înainte să salveze. Grupul este creat numai ca provizoriu. Pentru confirmare, deschideți una dintre camerele grupului, introduceți numărul chitanței și schimbați statusul; statusul și numărul chitanței se aplică întregului grup.

### Procedura de la 20:30
Rezervările individuale cu sursa exactă „Direct”, create în ziua sosirii și fără reconfirmare, trec automat în „Neconfirmată” la/după 20:30. Verificarea rulează la fiecare 30 de secunde cât timp aplicația este pornită și la următoarea accesare după ora-limită. Deschideți rezervarea și apăsați „Reconfirmă rezervarea pentru astăzi”; sistemul verifică din nou dacă respectiva cameră este disponibilă. Rezervările de grup sunt excluse din această procedură și rămân supuse regulii chitanței.

**Notă pentru testare:** programarea locală funcționează numai cât timp procesul aplicației este pornit. Într-o versiune găzduită, procedura trebuie mutată într-un scheduler/worker de producție și monitorizată. Rapoartele includ doar rezervările confirmate, cazate sau plecate; provizoriile, neconfirmatele și anulatele sunt excluse din camerele vândute și venitul estimat.


## v6 — export Excel .xls

- Butonul „Generează raport Excel (.xls)” descarcă un fișier în format Excel 97–2003 (BIFF8), cu foi „Rezumat”, „Pe corp” și „Pe cameră”.
- Fișierul este descărcat prin browser și poate fi salvat local în locația aleasă.
- Dependența `xlwt` este instalată automat prin `pip install -r requirements.txt`.
- Versiunea schemei bazei de date este verificată și se creează backup înainte de actualizarea unei baze mai vechi.

## v7-test — panou de recepție
Pagina principală include acum un rezumat zilnic, sosiri, plecări, lista de reconfirmări pentru procedura 20:30, camere pentru noaptea curentă și căutare rapidă în rezervările viitoare. Soldurile afișate sunt estimative (tarif × nopți minus avans), deoarece această versiune nu are încă un registru complet de plăți.


## v8 — selecție camere de grup și mentenanță

- Telefonul persoanei de contact este obligatoriu la rezervările de grup, atât în formular cât și pe server.
- Camerele de grup se selectează prin checkbox-uri; lista se actualizează când se schimbă sosirea sau plecarea și arată doar camerele disponibile pentru întregul interval. Verificarea este repetată la salvare.
- Administratorul are secțiunea „Camere / mentenanță” pentru marcarea unei camere ca defectă, cu motiv opțional, și reactivarea ei după remediere. Camerele defecte nu pot primi rezervări noi, nu apar în lista de camere disponibile și sunt excluse din capacitatea rapoartelor. Rezervările existente nu sunt șterse automat; acestea trebuie verificate separat.
- V10: exportul Excel folosește fallback CSV UTF-8 cu separator `;` dacă generatorul XLS eșuează; există și un buton separat CSV.
- Coloanele de mentenanță sunt adăugate prin migrare; se face copie de siguranță înainte de migrarea bazei mai vechi.


## v9-test — remedieri și autocomplete

- Formularul de grup încarcă automat camerele disponibile și permite bifarea lor; lista se actualizează când schimbați data sosirii sau plecării. Dacă apare o problemă de sesiune sau server, mesajul este afișat în formular.
- Exportul `.xls` folosește un interval de filtrare calculat fără a accesa un atribut inexistent al obiectului `xlwt` worksheet. Păstrați dependențele instalate cu `pip install -r requirements.txt`.
- În câmpul „Nume client” sau „Nume grup/persoană de contact”, începeți să tastați cel puțin două caractere pentru a primi sugestii din rezervările anterioare. Selectarea sugestiei completează câmpul; datele noi intră în lista de sugestii după ce sunt salvate într-o rezervare. Sugestiile folosesc numai numele, nu telefonul sau e-mailul.
- Versiunea nu schimbă structura bazei de date. Faceți totuși o copie separată a fișierului `motel.db` înainte de testare și porniți aplicația dintr-un folder nou.


### V10 – testare
- Selectorul de camere verifică disponibilitatea pentru toate nopțile alese și grupează opțiunile pe Corp A, Corp B și Corp C. Camerele ocupate sau defecte nu sunt afișate, iar serverul verifică din nou înainte de salvare.
- La editarea unei rezervări de grup, introducerea numărului chitanței și salvarea afișează o confirmare pentru aplicarea la întregul grup.
- Exportul statistic este disponibil în XLS și CSV; dacă generatorul XLS întâmpină o eroare, aplicația livrează un CSV compatibil cu Excel în locul paginii Internal Server Error.


## V11 (funcții păstrate în V12)
- Modulul de cameriste a fost introdus inițial cu o vedere pe trei zile; în V12 este simplificat la ziua curentă.
- Anularea grupului se găsește la editarea unei rezervări care aparține unui grup.
- Raportarea structurată este extinsă în V12 la XLSX cu formule și grafice.
- Migrarea bazei de date păstrează rezervările și extinde schema fără a reseta inventarul.
