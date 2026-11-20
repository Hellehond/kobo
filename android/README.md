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

## Installeren

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

GitHub bouwt de app bij elke wijziging in de map `android` op de hoofdtak en zet het APK-bestand
op de Releases-pagina. Android installeert een update alleen over de bestaande app heen als die met
dezelfde sleutel is ondertekend. Die sleutel staat niet in de repository. Je zet hem eenmalig als
geheim in GitHub, onder **Settings**, **Secrets and variables**, **Actions**:

| Naam | Waarde |
|---|---|
| `KOBOSYNC_KEYSTORE_BASE64` | Het sleutelbestand `kobosync-release.p12`, omgezet naar base64 |
| `KOBOSYNC_KEYSTORE_PASSWORD` | Het wachtwoord van dat bestand |

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
