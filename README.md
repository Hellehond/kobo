# kobosync

Een kleine server die je thuis draait, zodat de leesvoortgang van je **eigen ebooks**
(gekocht bij uitgeverijen, bol, Google Play zonder DRM, enz.) tussen je Kobo e-readers
wordt gesynchroniseerd. Precies zoals dat nu al gebeurt voor boeken uit de Kobo store.

## Waarom werkt het nu niet?

Kobo synchroniseert de leespositie alleen voor boeken die via de Kobo-server op het
toestel zijn gekomen. Een boek dat je via USB op de e-reader zet, kent de Kobo-server
niet. Er is dus niemand om de positie aan door te geven.

kobosync speelt die rol voor je eigen boeken:

1. Je zet je EPUB-bestanden in één map op een computer of NAS.
2. Beide e-readers praten met kobosync in plaats van rechtstreeks met Kobo.
3. kobosync biedt je eigen boeken aan alsof ze in je Kobo-bibliotheek staan.
   De e-readers downloaden ze en sturen de leespositie terug.
4. Alles wat over echte Kobo-aankopen gaat, stuurt kobosync door naar Kobo.
   De winkel, je gekochte boeken en hun synchronisatie blijven gewoon werken.

## Wat heb je nodig?

- Een computer, NAS of Raspberry Pi die aan staat wanneer je leest en die de e-readers
  via wifi kunnen bereiken.
- Python 3.9 of nieuwer, of Docker.
- Je ebooks als EPUB of KEPUB **zonder DRM**. Boeken met Adobe-DRM kan geen enkel
  programma zo aanbieden. Boeken met een watermerk (zoals de meeste Nederlandse
  uitgeverijen gebruiken) werken prima.
- Optioneel: [kepubify](https://pgaskin.net/kepubify/). Daarmee worden EPUB's omgezet
  naar KEPUB, het eigen formaat van Kobo. Dat geeft een preciezere leespositie, de
  "tijd tot einde hoofdstuk" en mooiere opmaak. Het Docker-image bevat kepubify al.

## Installeren

Er zijn drie manieren om kobosync te draaien:

| Manier | Synchroniseren | Kosten | Stappenplan |
|---|---|---|---|
| Thuis, alleen in je eigen netwerk | Alleen thuis | Geen | Hieronder |
| Thuis, online via een Cloudflare Tunnel | Overal | Alleen een domeinnaam | [deploy/cloudflare-tunnel](deploy/cloudflare-tunnel/README.md) |
| Gehuurde server met Caddy | Overal | Ongeveer 5 euro per maand plus domein | [deploy/vps](deploy/vps/README.md) |

Kies je een van de online manieren, volg dan het stappenplan in die map en sla de rest
van deze paragraaf over.

### Met Docker (aanbevolen)

```sh
git clone <deze repository> kobosync
cd kobosync
docker compose up -d
docker compose logs kobosync     # toont de api_endpoint-regel voor je e-readers
```

Zet je boeken in de map `library` naast `docker-compose.yml`.

### Zonder Docker

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m kobosync --library /pad/naar/boeken serve
```

Bij de start toont kobosync een regel zoals:

```
api_endpoint voor de e-readers: http://<ip-van-deze-machine>:8085/kobo/3f9c0e...
```

Het lange stuk na `/kobo/` is je persoonlijke token. Het staat ook in `data/token.txt`.

## De e-readers instellen (op beide toestellen)

1. Sluit de Kobo met USB aan op je computer.
2. Open op het toestel het verborgen bestand `.kobo/Kobo/Kobo eReader.conf`.
   Op een Mac zie je verborgen mappen met Cmd+Shift+punt.
3. Zoek het blok `[OneStoreServices]` en vervang de regel die met `api_endpoint=`
   begint door jouw adres, bijvoorbeeld:

   ```
   [OneStoreServices]
   api_endpoint=http://192.168.1.20:8085/kobo/3f9c0e...
   ```

   Gebruik het IP-adres van de machine waar kobosync draait.
   Bewaar de oude regel ergens, dan kun je altijd terug.
4. Werp het toestel netjes uit en tik op **Synchroniseren**.

Je eigen boeken verschijnen nu in je bibliotheek. Lees een stuk op het ene toestel,
synchroniseer, en synchroniseer daarna het andere toestel. Dat opent het boek op
dezelfde plek.

Let op: als je het toestel ooit uitlogt of terugzet naar de fabrieksinstellingen,
moet je stap 3 opnieuw doen.

## Dagelijks gebruik

Alle opdrachten op een rij staan in de [cheatsheet](CHEATSHEET.md).


- **Boek toevoegen:** zet het bestand in de bibliotheekmap. Een submap wordt een collectie.
  Bij de volgende synchronisatie staat het op beide toestellen.
- **Boek verwijderen:** haal het bestand uit de map. Het verdwijnt van beide toestellen.
  Verwijder je het op een toestel zelf, dan verdwijnt het ook van het andere.
  Terughalen kan met `python -m kobosync list` en `python -m kobosync restore <id>`.
- **Overzicht:** open `http://<ip>:8085/kobo/<token>/status` in een browser. Je ziet
  per boek de status en hoe ver je bent, en wanneer elk toestel voor het laatst
  synchroniseerde.

## Wat kobosync aan je boeken verbetert

kobosync geeft de Kobo's een verbeterde kopie van elk boek. Je originele bestanden
blijven altijd ongewijzigd. Boeken met vaste opmaak, zoals stripboeken en kinderboeken
met plaatjes, en boeken met DRM worden niet aangepast.

- **Auteurs apart.** Een auteursveld als "Thomas Heerma van Voss en Maartje Wortel" wordt
  opgesplitst in twee auteurs. Dat werkt ook met "og", "and", "&" en een puntkomma.
  Illustratoren en vertalers tellen niet meer als auteur.
- **Mappen worden collecties.** Een boek in de map `Thrillers` komt op beide Kobo's in de
  collectie "Thrillers". Submappen worden "Thrillers / Noors". Boeken direct in de
  bibliotheekmap komen in geen collectie. Je beheert deze collecties via de mappen:
  wijzig je er een op de Kobo, dan zet de volgende synchronisatie hem terug.
  Collecties die je zelf op de Kobo maakt, blijven gewoon via Kobo werken.
- **Je eigen lettergrootte en marges werken overal.** Vaste maten die uitgevers in hun
  opmaak zetten, zoals `font-size: 14px`, worden omgezet naar relatieve maten. Dan
  reageren alle pagina's op de instellingen van je Kobo.
- **Het boek opent bij het begin.** Rechtenpagina's, watermerkpagina's en colofons aan
  het begin van een boek gaan naar het einde. De cover, de titelpagina, de opdracht en
  het motto blijven op hun plek.

Elk onderdeel kun je uitzetten, zie de instellingen hieronder. Verander je een instelling,
dan verwerkt kobosync alle boeken opnieuw.

Staat een boek al op je Kobo, dan krijgt het de nieuwe versie pas als je het opnieuw
downloadt. Houd het boek op de Kobo ingedrukt, kies verwijderen, en kies dan de optie die
alleen de download van dit toestel verwijdert. Kies niet de optie die het boek uit je
bibliotheek haalt, want dan verdwijnt het van beide toestellen. Tik daarna weer op het
boek om het te downloaden. Je leespositie blijft bewaard.

Boeken die al via USB op een toestel staan, worden niet automatisch gekoppeld.
Verwijder die USB-kopie en laat het boek via kobosync binnenkomen. De leespositie van
de USB-kopie neemt Kobo niet mee.

## Instellingen

Alles is in te stellen met omgevingsvariabelen:

| Variabele | Standaard | Betekenis |
|---|---|---|
| `KOBOSYNC_LIBRARY` | `./library` | Map met je EPUB/KEPUB-bestanden |
| `KOBOSYNC_DATA` | `./data` | Database, covers, omgezette bestanden en token |
| `KOBOSYNC_TOKEN` | automatisch | Eigen token in plaats van het gegenereerde |
| `KOBOSYNC_PUBLIC_URL` | leeg | Adres waarlangs de e-readers de server bereiken, nodig achter een reverse proxy |
| `KOBOSYNC_PROXY_STORE` | `true` | Op `false` zetten om niets naar Kobo door te sturen. Dan werken winkel en Kobo-aankopen niet meer. |
| `KOBOSYNC_PORT` | `8085` | Poort |
| `KOBOSYNC_KEPUBIFY` | zoekt in PATH | Pad naar kepubify, of `none` om het uit te zetten |
| `KOBOSYNC_SPLIT_AUTHORS` | `true` | Auteursvelden met meerdere namen opsplitsen |
| `KOBOSYNC_FOLDER_COLLECTIONS` | `true` | Mappen als collecties op de Kobo's zetten |
| `KOBOSYNC_FIX_STYLES` | `true` | Vaste lettergroottes en marges omzetten naar relatieve maten |
| `KOBOSYNC_MOVE_FRONT_MATTER` | `true` | Rechtenpagina's en colofons naar het einde verplaatsen |
| `KOBOSYNC_SCAN_INTERVAL` | `30` | Hoe vaak (seconden) de map hooguit opnieuw wordt gelezen |

## Beveiliging

Het token in de URL is de enige toegangscontrole. Iedereen met die URL kan je boeken
downloaden. Draai kobosync daarom alleen in je thuisnetwerk, of zet het online met HTTPS
volgens een van de stappenplannen in de map `deploy`. Deel de URL met niemand.

## Ontwikkeling

```sh
pip install -r requirements-dev.txt
python -m pytest
```

De server implementeert het deel van de Kobo store-API dat e-readers voor hun
bibliotheek gebruiken: `/v1/library/sync`, de reading state (`/v1/library/<id>/state`),
metadata, covers en downloads. Al het andere wordt naar `storeapi.kobo.com` doorgestuurd.
De aanpak is dezelfde als die van de Kobo-sync in Calibre-Web.
