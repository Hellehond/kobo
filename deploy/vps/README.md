# Optie 3: een gehuurde server (VPS) met Caddy

kobosync draait op een kleine server in een datacenter. Caddy staat ervoor en regelt
automatisch een gratis HTTPS-certificaat. Thuis hoeft niets aan te staan.

**Kosten:** een VPS kost ongeveer vier tot vijf euro per maand, bijvoorbeeld de kleinste
server bij Hetzner. Daarbij komt een domeinnaam van een paar euro per jaar.

## Wat je nodig hebt

- Een VPS met Ubuntu of Debian. De kleinste variant is ruim voldoende.
- Een domeinnaam. Bij welke partij maakt niet uit.

## Stap 1: server en domein

1. Maak de server aan en noteer het IP-adres.
2. Maak bij je domeinbeheerder een **A-record** aan:
   naam `kobo`, waarde het IP-adres van de server.
   Het kan tot een uur duren voordat dit overal werkt.
3. Log in op de server en installeer Docker:

   ```sh
   ssh root@<ip-adres>
   curl -fsSL https://get.docker.com | sh
   ```

4. Zet een firewall aan die alleen SSH en webverkeer doorlaat:

   ```sh
   apt install -y ufw
   ufw allow 22/tcp && ufw allow 80/tcp && ufw allow 443
   ufw enable
   ```

   Heeft je provider een eigen firewall, zoals de Hetzner Cloud Firewall, dan kun je
   daar dezelfde drie poorten openzetten.

## Stap 2: kobosync starten

```sh
git clone https://github.com/Hellehond/kobo.git /opt/kobosync
cd /opt/kobosync/deploy/vps
cp .env.example .env
openssl rand -hex 16          # geeft een willekeurig token
nano .env                     # vul DOMAIN en KOBOSYNC_TOKEN in
docker compose up -d --build
docker compose logs -f
```

Na een halve minuut heeft Caddy het certificaat. Controleer in een browser:

```
https://kobo.jouwdomein.nl/kobo/<jouw KOBOSYNC_TOKEN>/status
```

## Stap 3: je boeken uploaden

De boeken komen in `/opt/kobosync/deploy/vps/library` op de server.
kobosync ziet nieuwe bestanden binnen een halve minuut.

- **Mac of Linux:**

  ```sh
  rsync -av ~/Ebooks/ root@<ip-adres>:/opt/kobosync/deploy/vps/library/
  ```

- **Windows:** gebruik WinSCP of FileZilla met het SFTP-protocol, je IP-adres en de
  gebruiker `root`. Sleep je boeken naar de map hierboven.
- **Automatisch:** wil je een map op je computer altijd gelijk houden met de server,
  dan kan dat met Syncthing. Dat vraagt wat meer instelwerk.

## Stap 4: de Kobo's instellen

Zet op beide toestellen in `.kobo/Kobo/Kobo eReader.conf`, onder `[OneStoreServices]`:

```
api_endpoint=https://kobo.jouwdomein.nl/kobo/<jouw KOBOSYNC_TOKEN>
```

Zie de hoofd-README voor de details van deze stap.

## Onderhoud

- **Bijwerken naar een nieuwe versie:**

  ```sh
  cd /opt/kobosync && git pull
  cd deploy/vps && docker compose up -d --build
  ```

- **Back-up:** de leesvoortgang staat in de map `data`. Kopieer die af en toe naar je
  eigen computer, op dezelfde manier als bij het uploaden.
- **Systeemupdates:** zet automatische beveiligingsupdates aan met
  `apt install -y unattended-upgrades`.

## Als het niet werkt

- **Caddy krijgt geen certificaat:** het A-record wijst nog niet naar de server, of
  poort 80 of 443 is dicht. Kijk in `docker compose logs caddy`.
- **De browser werkt, de Kobo niet:** controleer of de `api_endpoint`-regel met
  `https://` begint en precies je token bevat.
