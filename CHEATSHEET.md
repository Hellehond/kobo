# kobosync cheatsheet

Alle Docker-opdrachten voer je uit in de map met het `docker-compose.yml` dat je gebruikt:

| Opstelling | Map |
|---|---|
| Thuis, zonder tunnel | `kobosync` |
| Cloudflare Tunnel | `kobosync/deploy/cloudflare-tunnel` |
| Gehuurde server | `/opt/kobosync/deploy/vps` |

Krijg je "permission denied" bij Docker, zet dan `sudo` voor de opdracht. Dat is op een
Synology-NAS meestal nodig.

## Server starten en stoppen

```sh
docker compose up -d --build     # starten, of opnieuw bouwen na een wijziging
docker compose ps                # draait alles?
docker compose restart kobosync  # herstarten
docker compose stop              # stoppen, alles blijft bewaard
docker compose start             # weer starten na stop
docker compose down              # stoppen en containers opruimen, je data blijft bewaard
```

## Meekijken wat er gebeurt

```sh
docker compose logs -f kobosync          # live meekijken, stoppen met Ctrl+C
docker compose logs --tail 100 kobosync  # de laatste 100 regels
docker compose logs -f cloudflared       # alleen bij de Cloudflare Tunnel
docker compose logs -f caddy             # alleen bij de gehuurde server
```

Controleren of kobosync antwoordt:

```sh
docker compose exec kobosync python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8085/health').read().decode())"
```

Dat geeft `{"status":"ok"}` als alles goed is.

## Boeken

```sh
docker compose exec kobosync python -m kobosync list         # alle boeken, status en voortgang
docker compose exec kobosync python -m kobosync scan         # boekenmap nu inlezen, niet wachten
docker compose exec kobosync python -m kobosync restore 12   # boek 12 terugzetten
```

- **Toevoegen:** zet het bestand in je boekenmap. Een submap wordt een collectie op de Kobo's.
- **Verwijderen:** haal het bestand uit je boekenmap. Het verdwijnt van beide Kobo's.
- **Terughalen na verwijderen op een Kobo:** zoek het nummer met `list` en gebruik `restore`.
  Staat er "missing" achter het boek, zet dan het bestand terug in de boekenmap.
- **Collectie hernoemen:** hernoem de map. De boeken en hun leesvoortgang gaan mee.
- **Boek naar een andere collectie:** verplaats het bestand naar de andere map.

Welke map je boekenmap en je datamap is:

```sh
docker inspect kobosync --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{println}}{{end}}'
```

De regel met `-> /library` is je boekenmap, de regel met `-> /data` je datamap.

## Token en statuspagina

```sh
docker compose exec kobosync python -m kobosync token   # toont je token
```

- **Statuspagina:** `https://<jouw adres>/kobo/<token>/status`, of `http://<ip>:8085/kobo/<token>/status` thuis.
- **Regel voor de Kobo's:** `api_endpoint=https://<jouw adres>/kobo/<token>`

## Bijwerken naar een nieuwe versie

```sh
cd <map van kobosync>          # de map waar je de repository hebt gekloond
git pull
cd <map met docker-compose.yml>
docker compose up -d --build
docker image prune -f          # oude versies opruimen
```

Je leesvoortgang, token en instellingen blijven bewaard. Boeken worden na een update
automatisch opnieuw verwerkt.

## Instellingen wijzigen

1. Open `.env` in de map met je `docker-compose.yml`.
2. Pas een instelling aan, bijvoorbeeld `KOBOSYNC_FIX_STYLES=false`. Alle instellingen
   staan in de README.
3. Laat de container de nieuwe instellingen inlezen:

   ```sh
   docker compose up -d
   ```

## Back-up

Je leesvoortgang staat in de datamap. Stop kobosync even, zodat de database niet
halverwege een wijziging wordt gekopieerd:

```sh
docker compose stop kobosync
tar czf ~/kobosync-backup-$(date +%Y%m%d).tar.gz data
docker compose start kobosync
```

Heb je bij `DATA_DIR` een eigen pad ingevuld, gebruik dat pad dan in plaats van `data`.

Terugzetten:

```sh
docker compose stop kobosync
tar xzf ~/kobosync-backup-20261030.tar.gz
docker compose start kobosync
```

## Op de Kobo

| Wat | Hoe |
|---|---|
| kobosync instellen | In `.kobo/Kobo/Kobo eReader.conf`, onder `[OneStoreServices]`, de regel `api_endpoint=` aanpassen |
| Terug naar gewoon Kobo | Dezelfde regel terugzetten naar `api_endpoint=https://storeapi.kobo.com` |
| Nieuwe versie van een boek | Alleen de download verwijderen en het boek opnieuw downloaden |
| Na uitloggen of fabrieksreset | De regel `api_endpoint=` opnieuw aanpassen |

Haal een boek op de Kobo niet uit je bibliotheek als je alleen de download wilt
vernieuwen. Dan verdwijnt het van beide toestellen.

## Zonder Docker

Vervang `docker compose exec kobosync python` door `.venv/bin/python`, en geef dezelfde
`--library` en `--data` mee als bij het starten:

```sh
.venv/bin/python -m kobosync --library ~/Ebooks --data ~/kobosync-data serve
.venv/bin/python -m kobosync --library ~/Ebooks --data ~/kobosync-data list
```

## Als het niet werkt

| Probleem | Eerst proberen |
|---|---|
| Kobo synchroniseert niet | `docker compose logs -f kobosync` en dan synchroniseren op de Kobo. Zie je niets binnenkomen, dan klopt de regel `api_endpoint=` niet of is de server niet bereikbaar. |
| Nieuw boek verschijnt niet | `python -m kobosync scan` uitvoeren en het bestand controleren: alleen `.epub` en `.kepub.epub` worden gelezen. |
| Boek staat er dubbel | Het boek stond er al via USB. Verwijder de USB-kopie op de Kobo. |
| Collectie is leeg op de Kobo | Kijk in de logs naar regels met "Collection". Daar staat hoeveel boeken kobosync in elke collectie heeft gestuurd. |
| `git pull` vraagt om een wachtwoord | De repository is privé. Stel een deploy key in, zie hieronder. |
| Cloudflare-fout 502 | `docker compose logs cloudflared`, en controleer dat de Public Hostname naar `kobosync:8085` wijst. |
| Geen HTTPS-certificaat op de server | `docker compose logs caddy`, en controleer het A-record en poort 80 en 443. |

## Een deploy key instellen voor `git pull`

Nodig als je repository privé is. De server krijgt dan alleen leestoegang tot deze ene
repository, en je hoeft nooit meer een wachtwoord in te vullen.

```sh
ssh-keygen -t ed25519 -f ~/.ssh/kobo_deploy -N ""
cat ~/.ssh/kobo_deploy.pub
```

Plak de getoonde regel op GitHub bij je repository, onder **Settings** en dan
**Deploy keys**. Zet **Allow write access** niet aan. Daarna, in de map van kobosync:

```sh
cat >> ~/.ssh/config <<'END'
Host github.com
  IdentityFile ~/.ssh/kobo_deploy
  IdentitiesOnly yes
END
git remote set-url origin git@github.com:Hellehond/kobo.git
git pull
```
