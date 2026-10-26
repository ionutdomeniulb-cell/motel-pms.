# Acces de pe telefon (Android / iOS) în rețeaua locală

## 1. Pornire pe NUC, accesibilă din rețea
```powershell
# cheia secretă se generează automat (secret.key); dacă o setați manual, minimum 32 de caractere
$env:MOTEL_HOST = "0.0.0.0"
py app.py
```
- Aflați adresa NUC-ului cu `ipconfig` (ex. `192.168.1.50`). Pe telefon deschideți `http://192.168.1.50:5000`, conectat la același Wi-Fi.
- Rezervați acea adresă în router (DHCP reservation), ca să nu se schimbe.
- Windows poate cere deschiderea portului (o singură dată, PowerShell ca administrator):
  `New-NetFirewallRule -DisplayName "PMS Popas" -Direction Inbound -Protocol TCP -LocalPort 5000 -Action Allow -Profile Private`
- Pagina folosește compresie și cache pentru fișierele statice, deci se încarcă rapid și pe Wi-Fi slab.

## 2. Sunet și alerte pe telefon — ce trebuie știut
Browserul permite sunetul numai după ce utilizatorul atinge pagina. De aceea, la deschidere apare o bară galbenă
„Sunet blocat de telefon — atingeți aici": **o atingere oriunde pe ecran activează sunetul**.
Dacă telefonul blochează din nou sunetul (după ce pagina a stat mult în fundal), bara reapare, nu se pierde în tăcere.

Recomandări pentru telefonul / tableta cameristelor:
- Lăsați pagina PMS deschisă, cu ecranul pornit (setați „Oprire ecran" la maximum sau „Niciodată").
- Volumul **media** trebuie să fie ridicat (pe iOS, butonul lateral de silențios nu oprește sunetul alertelor).
- Android: dezactivați „Optimizarea bateriei" pentru Chrome; nu închideți aplicația din multitasking.
- iOS: Setări → Afișaj → Blocare automată → Niciodată (cel puțin cât lucrează cameristele).
- Dacă fila stă în fundal sau ecranul se blochează, browserul oprește sunetul și cronometrele. La revenire alertele se recuperează
  imediat (bannerul apare, sunetul reia după o atingere), dar în timpul blocării telefonul nu poate suna.

Indicatorul din colțul dreapta-jos arată starea: „🔔 Alerte active", „🔇 Sunet blocat" sau „⚠ Fără conexiune la PMS" (nu s-a primit răspuns de peste 30 s).

## 3. HTTPS (recomandat pentru tablete dedicate)
Pe conexiune HTTP simplă, browserele mobile **nu permit** „ecran activ" (Wake Lock) și notificările din browser.
Cu HTTPS le puteți activa din panoul de lângă clopoțel.
1. Pe NUC instalați [mkcert](https://github.com/FiloSottile/mkcert) și rulați: `mkcert -install`, apoi `mkcert 192.168.1.50` (adresa NUC-ului).
2. Porniți aplicația cu:
   ```powershell
   $env:MOTEL_SSL_CERT = "C:\cale\192.168.1.50.pem"
   $env:MOTEL_SSL_KEY  = "C:\cale\192.168.1.50-key.pem"
   py app.py
   ```
3. Pe telefon instalați certificatul rădăcină mkcert (`mkcert -CAROOT` → `rootCA.pem`):
   Android: Setări → Securitate → Certificate → Instalează certificat CA. iOS: trimiteți fișierul, instalați profilul,
   apoi Setări → General → Despre → Setări de încredere a certificatelor → activați.
4. Deschideți `https://192.168.1.50:5000`.

## 4. Pictogramă pe ecranul principal
Chrome (Android): meniu ⋮ → „Adaugă pe ecranul principal". Safari (iOS): Partajare → „Adăugare la ecranul principal".
Aplicația se deschide pe tot ecranul, fără bara browserului.

## 5. Ore de check-in și check-out
Implicit 12:00 / 13:00. Se pot schimba: `$env:MOTEL_CHECKIN_TIME="12:00"`, `$env:MOTEL_CHECKOUT_TIME="13:00"`.
Pragul de „ocupare redusă" pentru formularul săptămânal: `$env:MOTEL_DEEPCLEAN_MAX_OCCUPIED="4"`.

## 6. Recepția de noapte
Program implicit 21:00–06:00 (`MOTEL_NIGHT_START`, `MOTEL_NIGHT_END`). Detalii în `NOAPTE.md`.

## 7. Sesiuni
Administratorul este deconectat după 30 de minute de inactivitate, restul personalului după 12 ore (`MOTEL_IDLE_ADMIN_MIN`, `MOTEL_IDLE_STAFF_MIN`). Interogările automate ale paginii nu țin sesiunea deschisă.
