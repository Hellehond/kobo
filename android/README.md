# kobosync voor Android

Een leesapp voor je telefoon die met je kobosync-server praat zoals een Kobo dat doet. Je
leest je eigen boeken en gaat verder op de zin waar je op je Kobo gebleven was, en andersom.

## Wat de app kan

- **Bibliotheek:** al je eigen boeken met cover, te filteren op bezig, ongelezen en uitgelezen.
- **Offline lezen:** een boek wordt gedownload als je het opent. Daarna heb je geen internet nodig.
- **Zelfde plek als op je Kobo:** de app gebruikt dezelfde positiemarkeringen als de Kobo. Bij het
  openen van een boek, en als je de app weer naar voren haalt, haalt hij de laatste positie op.
- **Lezen:** tik op de rand of veeg om te bladeren, of gebruik de volumeknoppen. Tik in het midden
  voor de inhoudsopgave en de leesinstellingen: lettergrootte, lettertype, regelafstand, marges en
  een lichte, sepia of donkere achtergrond.
- **Nieuwe versie van een boek:** verwerkt de server een boek opnieuw, dan haalt de app de nieuwe
  versie vanzelf op als je het opent.

## Beperkingen

- **Alleen je eigen boeken.** Kobo-aankopen hebben DRM en openen alleen in de app van Kobo.
- **De exacte zin werkt alleen met KEPUB.** De Docker-versie van kobosync stuurt elk boek als KEPUB.
  Zonder kepubify valt de app terug op het percentage, en dan kom je op ongeveer de goede pagina uit.
- **Nog niet:** markeringen, notities, het woordenboek en leestijd in de statistieken.

## Installeren via Google Play

Kan je telefoon geen APK-bestanden installeren, gebruik dan een interne test in je Google Play
Console. Je installeert de app dan via de Play Store. Een interne test wordt niet door Google
beoordeeld en staat binnen een paar minuten klaar. Alleen de mensen die je zelf toevoegt, zien
de app.

### Eenmalig instellen

1. Kies in de [Play Console](https://play.google.com/console) **Create app**. Naam `kobosync`,
   type **App**, **Free**. Vink de verklaringen aan.
2. Ga naar **Testing**, **Internal testing**, tabblad **Testers**. Maak een e-maillijst met het
   Google-account van je telefoon en sla op.
3. Kies **Create new release**. Laat Google de ondertekening beheren (**Play App Signing**).
   De sleutel uit deze repository wordt dan je uploadsleutel.
4. Upload het bestand `kobosync-….aab` van de Releases-pagina, of het bestand dat je kreeg.
   Kies **Next** en dan **Save and publish** of **Start rollout to Internal testing**.
5. Kopieer op het tabblad **Testers** de link onder **How testers join your test**. Open die op
   je telefoon, kies **Accept invite**, en installeer de app vanuit de Play Store.

Vraagt de Play Console eerst om gegevens over de app, gebruik dan deze antwoorden:

| Vraag | Antwoord |
|---|---|
| Privacybeleid | `https://github.com/Hellehond/kobo/blob/main/docs/privacy.md` |
| Toegang tot de app | Er is een eigen server nodig. Geef aan dat de app zonder inlog geen inhoud toont. |
| Advertenties | Nee |
| Gegevensveiligheid | Geen gegevens verzameld of gedeeld. De app praat alleen met een server die de gebruiker zelf instelt. |
| Doelgroep | 18 jaar en ouder |

### Updates

Een nieuwe versie upload je op dezelfde manier: een nieuwe release in **Internal testing** met
het nieuwste AAB-bestand. Je telefoon werkt de app daarna zelf bij via de Play Store. Een upload
moet altijd een hoger versienummer hebben dan de vorige. De bestanden van GitHub hebben dat
vanzelf.

### Updates automatisch naar Play sturen

Dit is optioneel. Dan zet GitHub elke nieuwe versie zelf in je interne test.

1. Maak in [Google Cloud](https://console.cloud.google.com) een project, zet de
   **Google Play Android Developer API** aan, en maak een **service account** met een JSON-sleutel.
2. Nodig in de Play Console onder **Users and permissions** het e-mailadres van dat service
   account uit. Geef het voor de app kobosync het recht om releases naar testtracks te zetten.
3. Zet de volledige inhoud van het JSON-bestand in GitHub als geheim `PLAY_SERVICE_ACCOUNT_JSON`.

De eerste versie moet je altijd zelf uploaden, zoals hierboven. Daarna doet GitHub het.

## Installeren als APK

1. Download het nieuwste `kobosync-….apk` van de
   [Releases-pagina](https://github.com/Hellehond/kobo/releases) op je telefoon.
2. Open het bestand. Android vraagt eenmalig of je browser of bestandsbeheer apps mag installeren.
3. Open de app en vul het adres van je server in. Dat is hetzelfde adres als de regel
   `api_endpoint` op je Kobo's, bijvoorbeeld `https://kobo.jouwdomein.nl/kobo/<token>`.

Een nieuwe versie installeer je op dezelfde manier. Die werkt de app bij, en je boeken en
instellingen blijven staan.

De server moet de versie van november 2026 of nieuwer zijn. Werk hem bij zoals in de
[cheatsheet](../CHEATSHEET.md) staat.

## Automatisch bouwen en de ondertekeningssleutel

GitHub bouwt de app bij elke wijziging in de map `android` op de hoofdtak en zet het APK- en
AAB-bestand op de Releases-pagina. Android installeert een update alleen over de bestaande app heen als die met
dezelfde sleutel is ondertekend. Die sleutel staat niet in de repository. Je zet hem eenmalig als
geheim in GitHub, onder **Settings**, **Secrets and variables**, **Actions**:

| Naam | Waarde |
|---|---|
| `KOBOSYNC_KEYSTORE_BASE64` | Het sleutelbestand `kobosync-release.p12`, omgezet naar base64 |
| `KOBOSYNC_KEYSTORE_PASSWORD` | Het wachtwoord van dat bestand |
| `PLAY_SERVICE_ACCOUNT_JSON` | Optioneel, voor automatische uploads naar Google Play |

Zonder deze geheimen bouwt en test GitHub de app wel, maar komt er geen release.

Bewaar het sleutelbestand en het wachtwoord op een veilige plek. Raak je ze kwijt, dan moet je de
app één keer verwijderen en opnieuw installeren. Je leesposities staan op de server en blijven dus
bewaard.

## Zelf bouwen

Je hebt JDK 21 en de Android SDK nodig.

```sh
cd android
./gradlew :app:testDebugUnitTest :app:assembleDebug
```

Het APK-bestand staat daarna in `app/build/outputs/apk/debug`.

## Hoe het werkt

- **Server:** `data/KoboApi.kt` gebruikt dezelfde API als de Kobo's, met de kop
  `X-Kobosync-Client`. Daardoor stuurt de server geen Kobo-aankopen mee.
- **Posities:** een Kobo noteert een positie als een bestand in het boek plus het id van een
  `koboSpan`. `reader/KoboPosition.kt` zoekt bij het bladeren de eerste zichtbare span op de pagina,
  en springt bij het openen naar de span die de server doorgeeft.
- **Weergave:** de [Readium](https://readium.org)-toolkit toont het boek.
- **Tests:** `ServerSampleTest` gebruikt antwoorden die van de echte server zijn opgenomen, zodat
  app en server bij elkaar blijven passen.
