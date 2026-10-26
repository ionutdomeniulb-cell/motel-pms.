## v17 · r1 — module, autentificare în 2 pași, copii automate (26.10.2026)
1. **Recepția de noapte:** cauza „nu se poate interacționa”: tarifele de noapte erau 0 după migrare (camerele apăreau „Tarif nesetat”), iar noaptea testată era ocupată 100%. Acum tarifele se completează automat o singură dată (Corp A 150 lei, B/C 180 lei; modificabile de administrator), camera liberă se apasă, prețul apare preselectat, se completează nume, persoane și plata, iar după validare camera devine „Ocupată”.
2. **Setări (administrator):** fiecare secțiune se poate opri, ca afișare și ca funcționare: reconfirmări, confirmarea „vine după 21:00”, starea camerelor, comunicarea cu cameristele, alertele, curățenia extinsă, recepția de noapte, „De încasat dimineața”, rezervările viitoare, pontajul, raportul șefului de tură. Modificările se înregistrează în audit.
3. **Verificat:** o cazare de noapte apare a doua zi în calendar și în raportul șefului de tură (test automat + test în browser).
4. **Calendar:** săgeți înapoi/înainte, buton „Azi”, glisare pe telefon.
5. **Utilizatori:** editare completă (nume, utilizator, rol, PIN nou, activ, resetare 2 pași, deconectare de pe toate dispozitivele); protecție împotriva rămânerii fără administrator.
6. **Recepția de noapte fără restricție orară:** comutator în Setări; programul de noapte și ora reconfirmării (implicit 20:30) se setează din Setări.
7. **Securitate:** autentificare în 2 pași pentru administratori (TOTP, coduri de rezervă, blocare după 5 coduri greșite, cod nefolosibil de două ori); sesiunile se închid automat la schimbarea rolului, PIN-ului sau dezactivare; server de producție (cheroot, cu HTTPS); copii automate zilnice verificate; `manage.py` pentru resetare din consola PC-ului.
8. **Ceas de test** (`MOTEL_TEST_NOW` / `porneste.ps1 -CeasTest`), cu bandă roșie pe toate paginile.
- Schema 13 (copie automată înainte de migrare). Teste: 140.

## v16 · r1 — securitate, recepție de noapte, grupuri (23.10.2026)
1. **Anulare grup corectată:** butonul vechi „Anulează selecția” anula tot grupul (opțiunea „tot grupul” era bifată implicit). Acum: „Anulează camerele bifate” sau „Anulează tot grupul”, fiecare cu fereastră de confirmare care listează camerele; serverul refuză orice cerere neconfirmată sau cu camere din alt grup.
2. **Număr de persoane obligatoriu** la rezervare, editare, grup și recepția de noapte (fără valoare implicită; serverul nu mai completează tăcut „1”).
3. **Șef de tură:** total încasări (informativ, pentru rapoarte comparative) al nopții + cazările de noapte separat (cash / de încasat dimineața).
4. **Recepție de noapte** (rol nou, 21:00–06:00): camere pe corpuri, cazare sau rezervare în camerele libere (nume, persoane, plată), sosiri târzii cu nume/telefon/observații, „A sosit” / „Anulează”; camerele cazate nu mai pot fi modificate de recepția de noapte. Vezi NOAPTE.md.
5. **Recepția de zi:** „Sosește după ora 21:00” + observații pentru recepția de noapte; confirmare automată la 21:00 a rezervărilor neconfirmate; panou „De încasat dimineața”.
6. **Tarif implicit pe cameră** (Camere / mentenanță), folosit la cazările de noapte.
7. **Securitate** (SECURITY.md): refuz implicit, cheie secretă aleatorie, CSP strictă cu nonce, antete de securitate, blocare pe utilizator, expirare la inactivitate, politică de PIN, neutralizarea formulelor în exporturi, validări cu limite, pagini de eroare generice, limitare API.
- Schema 12 (copie automată înainte de migrare). Teste: 120.

## v15 · r2 — corecturi și funcții noi (23.10.2026)
- **Corectat:** calendarul avea rândurile și coloanele decalate față de numele camerelor, din cauza etichetei de stare adăugată în r1. Eticheta a fost eliminată; geometria este identică cu V13 (verificat prin măsurare în browser: 25 de camere, aceeași înălțime și aceleași poziții). Starea camerelor rămâne în panoul „Starea camerelor acum" și pe pagina cameristelor.
- **Pontaj cameriste** (Administrator → Pontaj): prima autentificare, ultima activitate, intervalul total și timpul conectat efectiv, pe zi și pe săptămână, cu export CSV lunar. Pauzele de peste 10 minute nu se numără ca timp conectat. Se înregistrează doar cameristele.
- **Rol „Șef de tură”** (se adaugă din Administrator → Utilizatori, cu utilizator și PIN): vede doar „Raport ocupare”, camerele ocupate în noaptea precedentă, numărul și gradul de ocupare, fără nume de clienți și fără alte pagini. Administratorul îl deschide din Rapoarte.
- **Versiunea** se afișează discret în subsolul fiecărei pagini (și în /api/v1/health): `v15 · r2 · 23.10.2026`.
- Bara „Sunet blocat” apare doar pentru cameriste sau după o alertă care nu a putut suna (nu mai apare inutil la recepție).
- Schema 11 (copie automată înainte de migrare). Teste: 71.

## v15-test — modificări din testele pe teren
1. **Rezervări viitoare și căutare rapidă:** rămân vizibile doar ultimele 3 rezervări create sau modificate; restul listei și căutarea se extind la cerere (se deschide automat când căutați).
2. **Stare automată a camerelor după oră:** după ora de check-out (13:00) o cameră cu plecare nefinalizată devine liberă singură; rămâne vizibilă rezervarea care intră în aceeași zi (check-in de la 12:00, fără check-in manual rămâne „sosire azi"). Se vede în panoul camerelor, în calendar (eticheta „· auto") și pe pagina cameristelor. Nu se modifică rezervările din baza de date; ambele părți primesc alertă („Cameră eliberată automat" / „Check-out neconfirmat").
3. **Hârtie igienică** adăugată la solicitări; serviciile se bifează (se pot combina). Solicitările vechi rămân neschimbate.
4. **Pagina cameristelor (mobil):** rămân vizibile doar sarcinile active; cele rezolvate se extind la cerere.
5. **Starea camerei și ora check-out-ului** în locul textului „Client cazat · nu se marchează…": ocupată (check-out data, ora), plecare azi până la 13:00, sosire azi, următoarea sosire.
6. **Formular săptămânal de curățenie extinsă** (8 puncte + observații, pe cameră): oferit cameristelor la autentificare în zilele cu cel mult 4 camere ocupate și cât timp mai sunt camere nefăcute în săptămână; salvare ca ciornă și trimitere către recepție (alertă + pagina „Rapoarte curățenie extinsă").
7. **Alerte de sunet regândite pentru telefon:** sunet din fișiere audio, deblocare la orice atingere, bară vizibilă când telefonul blochează sunetul, detectarea redării „agățate" cu refacerea elementului audio, timeout și reluare automată a cererilor de rețea, indicator de conexiune, recuperare la revenirea în pagină (inclusiv din cache iOS), ecran menținut aprins unde browserul permite, frecvență redusă când pagina e în fundal.
- **Optimizare pentru telefon:** compresie gzip (calendarul: ~134 KB → ~10 KB), cache pentru fișiere statice, pictogramă și manifest pentru ecranul principal, HTTPS opțional (`MOTEL_SSL_CERT` / `MOTEL_SSL_KEY`), elemente tactile mai mari. Vezi MOBIL.md.
- Schema 10 (copie automată înainte de migrare). Teste: 63.

## v14-test — stări cameră și pregătire pentru Home Assistant
- Panou nou pe prima pagină, „Starea camerelor acum": cele 25 de camere pe corpuri, cu stare clară (ocupată, plecare azi, sosire azi, liberă curată, liberă de verificat, defectă); apăsarea unei camere deschide rezervarea sau creează una pentru astăzi.
- Motor unic de stare pentru camere (`room_state.py`), cu aceleași reguli ca modulul cameristelor.
- Cod stabil pe cameră (ex. `camera_101`), nemodificat la redenumire; schema 9 (doar adaugă, cu copie automată în `backups`).
- Coadă de evenimente (`room_events`) alimentată automat din operațiunile existente, inclusiv procedura de la 20:30; o eroare aici nu blochează rezervarea.
- API de integrare v1, doar citire, cu token (`integration_api.py`, vezi INTEGRARE.md); dezactivat implicit; fără nume de clienți în răspunsuri.
- `MOTEL_HOST` / `MOTEL_PORT` pentru acces din rețea; aplicația refuză pornirea în rețea cu cheia secretă implicită.
- Teste: 40 (față de 30); au fost corectate două teste rămase în urmă față de interfață.
- **Alerte recepție ↔ cameriste (sunet + text):** solicitare nouă către cameristă (urgentă, persistentă, cu sunet repetat, titlu care clipește, vibrație), solicitare rezolvată, cameră marcată curată/redeschisă, check-out și mentenanță. Fiecare persoană primește doar ce o privește, fără alerte pentru acțiunile proprii. Control pentru sunet, teste de alertă și notificări din browser. Vezi TESTARE_ALERTE.md.
- **Panoul „Solicitări și stare camere" restrâns:** rămân vizibile doar acțiunile în desfășurare, plus un rezumat cu contoare; istoricul și starea camerelor se extind la cerere (starea se reține).
- **Actualizare live fără reîncărcarea paginii** (recepție și cameriste), ca sunetul activat să nu se piardă.
- **Corectat:** pagina cameristei nu se actualiza deloc singură (scriptul era în afara blocului de șablon, iar endpoint-ul de sincronizare era blocat pentru cameriste), iar alertele vechi priveau doar solicitările create de recepție. Solicitările apar acum la începutul paginii cameristei.
- Teste: 47.

## v12-test — housekeeping, rol Cameristă și export XLSX
- Modulul Cameriste afișează doar ziua curentă, grupează camerele pe corpuri și distinge camerele ocupate, eliberate astăzi, curate și neverificate. Camerele ocupate nu pot fi marcate ca pregătite pentru o nouă cazare.
- Recepția poate trimite solicitări de curățenie, schimb prosoape sau ambele; statusul și numele persoanei care rezolvă sunt partajate prin baza de date.
- Adăugat profil de acces Cameristă cu PIN propriu și acces restricționat la modulul de housekeeping.
- Exportul rapoartelor este trecut la XLSX cu foi structurate, formule, filtre, tabele și grafice de ocupare. Camerele defecte sunt excluse atât din capacitate, cât și din numărătorul gradului de ocupare.
- Migrare SQLite la schema v8 fără ștergerea rezervărilor; se adaugă tabelul de solicitări și profilul de acces.

# Jurnal modificări

## v3-test — 15.10.2026
- Autentificare cu PIN individual și configurare inițială pentru administrator.
- Roluri administrator/recepție, creare/dezactivare utilizatori și resetare PIN de către administrator.
- Protecție CSRF pentru formularele POST și limitare temporară a încercărilor de autentificare.
- Jurnal de audit pentru operațiunile importante.
- Celulele libere ale calendarului deschid formularul cu camera și data precompletate.
- Modul local de test Oblio cu cheie idempotentă, jurnalul încercărilor și blocarea cererilor duplicate.
- Backup automat înainte de prima migrare a bazei de date; păstrarea rezervărilor existente.

Notă: integrarea live cu API-ul Oblio nu este activată în această versiune. Butonul de test nu emite document fiscal.

## v4 — calendar, audit, reports and user management
- The calendar's selected date is preserved when returning from a cell-started reservation; camera and check-in remain prefilled from the selected cell.
- Added admin-only reports for a selected date period: room nights sold, occupancy, estimated accommodation revenue, building and room breakdown.
- Added permanent account deletion with protections against self-deletion and deleting the last administrator. Historical audit events remain available.
- Added per-user creator colors on reservation bars and a legend; creator name/color are stored as snapshots on each new reservation.
- Audit events are stored in SQLite and appended to `logs/audit.log` (UTF-8 JSON Lines), with a downloadable Notepad-friendly TXT export.
- Schema migration version 3 adds booking creator metadata without removing existing reservations and makes a pre-migration database backup.


## v5 — raport Excel, grupuri și procedură 20:30

- Rapoartele administratorului pot fi descărcate ca registru Excel `.xlsx`, cu foi separate pentru rezumat, corpuri și camere. Fișierul se descarcă în locația aleasă de browser.
- Tariful pe noapte este obligatoriu și trebuie să fie mai mare decât 0 pentru rezervările noi și editate.
- Rezervare de grup într-o singură acțiune: mai multe camere, aceeași perioadă și persoană de contact; toate camerele se creează provizoriu.
- Confirmarea grupului necesită numărul chitanței și se propagă tuturor camerelor din grup.
- Procedură automată: după ora 20:30, rezervările individuale cu sursa „Direct”, sosire în ziua curentă și fără reconfirmare devin „Neconfirmată”; evenimentul este jurnalizat în SQLite și în `logs/audit.log`. Un proces de verificare rulează la 30 de secunde cât timp aplicația locală este pornită, iar verificarea se repetă și la următoarea cerere.
- Rezervările neconfirmate nu mai blochează camera și nu intră în rapoartele de camere vândute. Pentru a reveni la confirmat, se verifică din nou disponibilitatea.
- Migrare SQLite la versiunea 4, cu backup automat înainte de actualizarea schemei.


## v6-test — export .xls

- Exportul rapoartelor a fost schimbat la format Excel 97–2003 `.xls`, cu foi pentru rezumat, corpuri și camere.
- Butonul de export descarcă fișierul local prin browser, cu numele raportului și intervalul selectat.
- A fost adăugată dependența `xlwt`, iar testul verifică semnătura unui fișier BIFF8.
- Schema SQLite este marcată versiunea 5, cu backup înainte de migrarea bazelor mai vechi.

## v7-test — panou zilnic pentru recepție
- Pagina principală începe cu un panou operațional pentru ziua curentă: camere disponibile, sosiri, plecări și camere rezervate/ocupate.
- Liste separate pentru sosirile și plecările zilei, cu acces direct la fișa rezervării și soldul estimat la plecare.
- Listă de reconfirmare pentru rezervările individuale directe create în ziua sosirii, conectată la procedura existentă de la 20:30.
- Acțiuni rapide pentru rezervare în ziua curentă și rezervare de grup.
- Căutare rapidă în rezervările viitoare după nume, telefon, e-mail sau cameră.
- Statisticile „ocupate astăzi” sunt calculate independent de perioada afișată în calendar, iar camerele inactive nu intră în calculul disponibilității.
- Nu s-au adăugat tabele sau migrări noi; datele și funcțiile anterioare sunt păstrate.


## v8-test — 2026-10-19
- Telefon obligatoriu pentru persoana de contact la rezervarea de grup.
- Înlocuită selecția multi-select cu checkbox-uri pentru camerele disponibile pe perioada aleasă; lista se reîncarcă la schimbarea datelor.
- Adăugată verificare server-side pentru camere ocupate și camere marcate ca defecte.
- Adăugată administrarea mentenanței camerelor pentru administrator, cu motiv și audit.
- Camerele defecte nu primesc rezervări noi și nu sunt incluse în capacitatea rapoartelor.
- Adăugat fallback de export Excel `.xls` pentru situația în care `xlwt` nu este instalat, prevenind eroarea 500 din cauza dependenței lipsă.
- Actualizată migrarea bazei de date la schema v6 și backupul pre-migrare.


## v9-test — 2026-10-19
- Remediată încărcarea camerelor la rezervarea de grup: scriptul JavaScript era în afara blocului de pagină și nu era randat de șablonul de bază. Acum este inclus în pagina formularului și se execută la încărcare și la modificarea perioadei.
- Adăugat mesaj de eroare vizibil dacă API-ul de disponibilitate nu răspunde cu JSON sau sesiunea a expirat.
- Remediată o cauză de eroare 500 la exportul `.xls`: eliminată referința la `sheet.nrows` (atribut care nu este disponibil pe obiectul worksheet `xlwt`); intervalul filtrului se calculează din numărul de camere/corpuri.
- Adăugat autocomplete pentru numele clientului/persoanei de contact: sugestiile sunt căutate în rezervările anterioare când se tastează cel puțin două caractere. API-ul este disponibil doar utilizatorilor autentificați și returnează cel mult 12 nume distincte.
- Adăugate teste automate pentru randarea scriptului de camere și autocomplete.
- Nu se adaugă tabele sau migrări de bază de date; rezervările existente nu sunt modificate.


## V10 – disponibilitate strictă, confirmare grup și export robust
- Listele de camere pentru rezervări individuale și de grup sunt filtrate după perioada selectată: camerele ocupate și camerele defecte nu sunt afișate ca opțiuni. Verificarea server-side rămâne activă pentru a preveni rezervările concurente.
- Camerele sunt grupate vizual pe Corp A, Corp B și Corp C, în ordine intuitivă.
- La salvarea unei camere dintr-un grup, dacă există număr de chitanță, aplicația întreabă dacă chitanța și confirmarea se aplică întregului grup. Alegerea afirmativă confirmă toate camerele și propagă numărul chitanței; alegerea negativă păstrează modificarea doar pe camera curentă.
- Exportul XLS este protejat cu fallback la CSV UTF-8 cu separator `;`, iar în rapoarte există și buton separat de export CSV pentru Excel.
- Teste suplimentare pentru excluderea camerelor ocupate/defecte, ordonarea pe corpuri, export CSV și confirmarea parțială/totală a grupului.


## V11 — operațiuni, rapoarte și cameriste
- Anulare rezervare de grup: integral sau camere selectate, cu confirmare explicită și audit.
- Raport XLS structurat în foi Rezumat, Pe corpuri, Pe camere, Date zilnice și Rezervări; export CSV fallback cu un rând per rezervare.
- Modul Cameriste optimizat pentru mobil, cu calendar pe trei zile și bifă verde pentru camere curate.
- Eliminat rândul duplicat de indicatori din pagina principală.
- Sesiunea de autentificare expiră la schimbarea zilei locale.
- Versiunea bazei de date ridicată la 7, fără ștergerea rezervărilor existente.

## V13 — actualizare recepție / cameriste
- Procedura de reconfirmare exclude acum din lista „De reconfirmat” rezervările cu `reconfirmed_at` completat; după apăsarea butonului, rezervarea confirmată nu mai rămâne afișată ca restantă.
- Adăugat endpoint autentificat de sincronizare pentru solicitările de housekeeping, actualizările rezervărilor și marcajele de curățenie.
- Calendarul recepției se reîncarcă automat la 30 secunde și urmărește schimbările de housekeeping la 5 secunde; reîncărcarea este amânată când utilizatorul completează un câmp sau are dialogul deschis.
- Modulul cameristelor verifică schimbările la 10 secunde și actualizează automat starea solicitărilor/curățeniei, fără scroll orizontal pentru solicitări pe mobil.
- Solicitările cameristelor sunt prezentate în carduri responsive cu camera, tipul serviciului, detaliile, statusul și ora locală a solicitării.
- Panoul recepției verifică solicitările noi la 5 secunde și redă un semnal sonor plus o notificare vizuală după ce utilizatorul a interacționat cu pagina (limitare standard a browserelor pentru redarea audio automată).
