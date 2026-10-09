# DigitXBD

A mobile-friendly printing-shop app for customers, invoices, payments, dues, expenses, investments, stock, online orders and document uploads. Includes dark mode, printable invoices, merchant QR images and optional Windows PDF printing.

**This public version starts empty.** It contains no customer records, accounts, uploaded documents, merchant QR or passwords. Keep the empty `seed.json`: the Docker build needs it.

## What you need

Install [Docker Desktop](https://docs.docker.com/get-started/get-docker/) on Windows/Mac, or Docker Engine with Compose on Linux. Start Docker and use Linux containers. You need internet for the first installation and a browser. Python, Node.js and React run inside Docker.

## Install on Windows

### 1. Download the project

Download this repository using **Code → Download ZIP** and extract it, or clone it with Git. Open the folder containing `compose.yaml`, `Dockerfile` and `Start-DigitXBD.ps1`. Right-click inside it and select **Open in Terminal**.

The folder can have any name: Compose uses the project name `digitxbd`. Use one installation per computer unless you deliberately change the project name and port.

### 2. Start the app

Paste this command into the terminal:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Start-DigitXBD.ps1
```

Wait until the app is running. The first build can take several minutes. Installation creates a private `.env` file with unique secrets. Keep it and leave `MIGRATE_TRACKER=0`; do not upload `.env` to GitHub.

### 3. Create your owner account

1. Open [http://localhost:8091](http://localhost:8091).
2. Open `.env` in Notepad. Copy only the value after `SETUP_TOKEN=`.
3. Paste it into the setup form.
4. Choose a username of 3–40 letters, numbers, dots, underscores or hyphens, and a password of at least 12 characters.
5. Sign in. Open **Settings** to enter your business details, public URL and original merchant Bangla QR image.

There is no default account. New installations contain no business records.

## Install on Mac or Linux

Open a terminal in the downloaded project folder. On Linux, prepare the uploads folder first:

```sh
sudo install -d -o 10001 -g 10001 -m 750 ./DigitXBD-Uploads
```

Then run these commands on Mac or Linux:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace python:3.12-slim python configure.py
docker compose up -d --build
```

Follow **Create your owner account** above; open `.env` with your preferred text editor.

## Use the app

| Page | Local address | Purpose |
|---|---|---|
| Owner dashboard | http://localhost:8091/login | Manage the shop |
| Shop upload | http://localhost:8091/order | Upload documents; the owner creates the invoice manually |
| Online order | http://localhost:8091/online_order | Place an order; the owner reviews the price and confirms its invoice |

Use **Counter & billing** for invoices and payments. Later payments settle the customer's existing balance without creating another sale. Investments and withdrawals are separate from expenses.

Find customer documents in **Files**. See [business workflows](WORKFLOW.md) and [Windows printer setup](PRINTING.md). The Windows printer connector is optional and requires separate setup.

Customers on other devices need your public domain: `localhost` works only on the app computer.

## Where data is stored

| Location | Contents |
|---|---|
| `DigitXBD-Uploads/` inside the project | Customer documents and merchant QR images on your local disk |
| Docker volume `digitxbd_digitxbd-data` | Database, accounts and financial records |
| `DigitXBD-Backups/` inside the project | Backups you save here yourself |
| `.env` | Private installation settings and secrets |

Docker mounts uploads at `/data/uploads`. Find original customer filenames through **Files**; avoid renaming stored files manually. Retention cleanup and permanent deletion can remove local documents.

For another location, set `UPLOADS_DIR` in `.env`, for example `UPLOADS_DIR=D:/ShopUploads`. Stop the app, move existing files, update the setting and restart. Linux folders must be writable by user ID 10001. Moving the project does not move Docker's database volume.

## Connect an existing Cloudflare Tunnel

1. Connect your cloudflared container to DigitXBD's network. Replace the placeholder with its actual container name:

   ```sh
   docker network connect digitxbd_default YOUR_CLOUDFLARED_CONTAINER
   ```

2. In Cloudflare, add a published application route for your domain with service **HTTP**, address **`web:8080`**. Both containers must share `digitxbd_default`.
3. Add that network as an external network in cloudflared's own Compose configuration so the connection survives recreation. Do not use `localhost:8091` inside cloudflared.
4. Set your actual domain in DigitXBD's `.env`:

   ```dotenv
   PUBLIC_URL=https://your-domain.com
   COOKIE_SECURE=1
   ```

5. Run `docker compose up -d`. Open your HTTPS domain and also enter it in **Settings → Public URL**. Check login and customer uploads.

Hosting providers can impose upload-size limits even though the app's former 16 MB and 32 MB limits are removed.

## Back up and restore

Regularly download **Settings → Download full backup**. Save it privately, preferably on another disk or computer. It includes records, accounts and available uploads.

To restore on a new computer:

1. Start a fresh installation, but do not create an owner account.
2. Create `DigitXBD-Backups` inside the project. Put the backup there as `backup.zip`; do not extract it.
3. From the project folder, run:

   ```sh
   docker compose stop web
   docker compose run --rm -v "./DigitXBD-Backups:/backup:ro" --entrypoint python web restore_backup.py /backup/backup.zip
   ```

4. Only after it reports **Restore complete**, run `docker compose up -d`.
5. Sign in with the account from the backup. Update the public URL if needed and pair the printer connector again.

## Everyday commands

Run these from the project folder:

| Task | Command |
|---|---|
| Start | `docker compose up -d` |
| Stop | `docker compose stop` |
| Check status | `docker compose ps` |
| Read recent errors | `docker compose logs --tail=50 web` |
| Rebuild after downloading updated source | `docker compose up -d --build` |

Before updating, download a backup and keep your `.env`, uploads and Docker volume. Replace source files without replacing private storage.

**Do not run `docker compose down -v`: it deletes the database volume.**

## Troubleshooting

- **Docker unavailable:** start Docker Desktop and wait until it is ready.
- **Port 8091 busy:** change `PORT` and `PUBLIC_URL` in `.env`, for example `PORT=8095` and `PUBLIC_URL=http://localhost:8095`, then run `docker compose up -d`.
- **Cannot find `.env`:** run installation first; some file browsers hide dot files.
- **Unexpectedly empty app:** check the Docker project/volume. Use a full backup when moving to a new computer.
- **Printer offline:** check Windows printing and follow [PRINTING.md](PRINTING.md).

## License

Licensed under the [MIT License](LICENSE).
Third-party components retain their respective licenses.