# Recepția de noapte

Pagină simplă, pentru telefon, folosită de persoana care asigură cazarea în afara programului recepției.

## Configurare (administrator, o singură dată)
1. **Utilizatori** → adăugați un cont cu rolul **Recepție noapte** (utilizator + PIN de 6–8 cifre, nu o serie simplă).
2. **Camere / mentenanță** → verificați **Tarif noapte (lei)**; din V17 este completat automat unde lipsea (Corp A 150 lei, Corp B/C 180 lei). Recepția de noapte vede prețul, dar nu îl poate schimba.
3. Pe telefonul de noapte: autentificare cu acest cont. Se deschide direct pagina „Recepție noapte”; alte pagini nu sunt accesibile.
   Administratorul o poate deschide din **Rapoarte → Recepție noapte**. Recepția de zi nu are acces la ea.

## Program
- Acțiunile sunt permise între **21:00 și 06:00**. În afara acestui interval pagina se poate doar vizualiza
  (administratorul poate acționa oricând, pentru verificări).
- După miezul nopții, totul se înregistrează pe noaptea care a început seara (ex. la 02:30, „noaptea de 23.10 → 24.10”).
- Orele și restricția orară se schimbă din **Administrator → Setări** (programul de noapte, închiderea recepției de zi, comutatorul „Restricție orară la recepția de noapte”). Tot acolo se poate opri complet modulul.

## Ce vede și ce poate face
- **Camerele pe corpuri**, cu stare: Liberă · Ocupată · Rezervată · Așteptat (sosire târzie) · Defectă. Fără nume sau alte detalii.
- **Cameră liberă** → apăsați pe ea:
  - **Cazează acum**: nume, număr de persoane (obligatoriu) și plata: *Încasat cash* sau *Se încasează la recepție dimineața*.
  - **Rezervă · vine mai târziu**: nume și număr de persoane; apare apoi la „Sosiri după ora 21:00”.
  - Cazarea de noapte este pentru **o noapte**; prelungirile se fac la recepția de zi.
- **Sosiri după ora 21:00**: nume, telefon (se poate apăsa pentru apel) și observația recepției de zi.
  - **A sosit · cazează** (cu alegerea plății) sau **Anulează rezervarea** (camera devine liberă).
- După cazare, camera **nu mai poate fi modificată** de la recepția de noapte. Starea se schimbă automat la ora de check-out (13:00)
  sau o modifică recepția de zi / administratorul.

## Legătura cu recepția de zi
- În formularul de rezervare: **Sosește după ora 21:00** + **Observații pentru recepția de noapte** (observațiile se acceptă doar pentru astfel de sosiri).
- La 21:00, rezervările neconfirmate cu sosire azi devin automat „vin după ora 21” și apar la recepția de noapte cu nume și telefon.
  Dacă între timp camera a fost dată altcuiva, rezervarea apare marcată cu avertisment și nu poate fi cazată.
- Dimineața, pe prima pagină apare **De încasat dimineața · cazări de noapte**, cu buton **Marchează încasat**.
- Șeful de tură vede totalul informativ al nopții și separat sumele cazărilor de noapte (cash / de încasat dimineața).
