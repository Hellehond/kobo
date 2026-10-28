# Optie 2: thuis draaien, online via een Cloudflare Tunnel

kobosync draait op je NAS, Raspberry Pi of een computer die altijd aan staat.
Een tweede container, `cloudflared`, legt een beveiligde verbinding naar Cloudflare.
Je Kobo's bereiken kobosync dan overal via `https://kobo.jouwdomein.nl`.
Je hoeft niets in je router open te zetten.

**Kosten:** de tunnel is gratis. Je hebt een eigen domeinnaam nodig, een paar euro per jaar.

## Wat je nodig hebt

- Een apparaat thuis met Docker. Op een Synology heet dat "Container Manager".
- Een domeinnaam waarvan Cloudflare de DNS beheert. Je kunt er een kopen bij Cloudflare
  zelf, of een bestaand domein naar Cloudflare verhuizen. Het gratis abonnement volstaat.

## Stap 1: de tunnel aanmaken bij Cloudflare

1. Log in op het Cloudflare-dashboard en open **Zero Trust**.
   De eerste keer vraagt Cloudflare je een teamnaam te kiezen en het gratis abonnement te
   kiezen. Dat vraagt om een betaalgegeven, maar het gratis abonnement kost niets.
2. Ga naar **Networks → Tunnels** en kies **Create a tunnel**.
3. Kies **Cloudflared** als type en geef de tunnel een naam, bijvoorbeeld `kobosync`.
4. Cloudflare toont nu installatiecommando's. Kies **Docker**. In het commando staat
   `--token` gevolgd door een lange tekst. **Kopieer alleen die lange tekst.**
   Voer het commando zelf niet uit.
5. Ga verder naar **Public Hostname** en vul in:
   - **Subdomain:** `kobo`
   - **Domain:** je domein
   - **Type:** `HTTP`
   - **URL:** `kobosync:8085`
6. Sla op.

## Stap 2: kobosync starten

```sh
git clone https://github.com/Hellehond/kobo.git kobosync
cd kobosync/deploy/cloudflare-tunnel
cp .env.example .env
openssl rand -hex 16          # geeft een willekeurig token
```

Open `.env` en vul in:

- `DOMAIN`: bijvoorbeeld `kobo.jouwdomein.nl`
- `TUNNEL_TOKEN`: de lange tekst uit stap 1.4
- `KOBOSYNC_TOKEN`: het token uit het `openssl`-commando
- `LIBRARY_DIR`: de map met je ebooks

Start daarna:

```sh
docker compose up -d --build
docker compose logs -f
```

In het Cloudflare-dashboard staat de tunnel nu op **Healthy**.

Controleer in een browser of dit je statuspagina toont:

```
https://kobo.jouwdomein.nl/kobo/<jouw KOBOSYNC_TOKEN>/status
```

## Stap 3: de Kobo's instellen

Zet op beide toestellen in `.kobo/Kobo/Kobo eReader.conf`, onder `[OneStoreServices]`:

```
api_endpoint=https://kobo.jouwdomein.nl/kobo/<jouw KOBOSYNC_TOKEN>
```

Zie de hoofd-README voor de details van deze stap.

## Als het niet werkt

- **De tunnel staat op "Down":** het `TUNNEL_TOKEN` klopt niet, of het apparaat heeft geen
  internet. Kijk in `docker compose logs cloudflared`.
- **De browser toont een Cloudflare-fout 502:** de tunnel werkt, maar vindt kobosync niet.
  Controleer of de URL bij de Public Hostname precies `kobosync:8085` is, met type `HTTP`.
- **De browser werkt, de Kobo synchroniseert niet:** zet in het gewone Cloudflare-dashboard
  van je domein onder **Security → Bots** de optie **Bot Fight Mode** uit. Die blokkeert
  soms de e-readers. Kijk ook onder **Security → Events** of er verzoeken worden geblokkeerd.

## Ook thuis rechtstreeks?

Dat is niet nodig, de tunnel werkt thuis ook. Wil je het toch, haal dan in
`docker-compose.yml` het hekje weg voor de `ports`-regels. Gebruik op de Kobo's dan
toch het `https://`-adres, anders werkt het onderweg niet.
