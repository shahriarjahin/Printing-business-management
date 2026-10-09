# Print with your Canon G3010

DigitXBD runs in Docker. A small Windows helper sends approved PDF jobs to your installed printer. Your existing orders, bills and customer balances stay separate from printing.

## First setup

1. Connect your Canon G3010 to the shop computer by USB or Wi-Fi. Install the Canon Windows driver. Check that Windows can print a normal document.
2. Install [SumatraPDF from its official website](https://www.sumatrapdfreader.org/download-free-pdf-viewer). The helper uses its PDF printing function.
3. Sign in to DigitXBD as owner. Open **Print queue** and click **Download Windows helper**. Extract the ZIP into a folder.
4. Click **Connect printer helper → Generate helper key** in DigitXBD. Copy the key. Keep it private.
5. In the extracted folder, run **Setup-Printer.ps1** in PowerShell. If Windows blocks it, open PowerShell in that folder and run:

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\Setup-Printer.ps1
   ```

6. Enter the app address: `http://localhost:8091` if Docker is on this computer, or `https://your-domain.com` for your published app. Enter the installed SumatraPDF path, the exact Windows printer name, and paste your helper key when asked.
7. Setup checks the connection without printing, then installs automatic startup. **Print queue** should show **Connected**. It starts at Windows sign-in, waits for Docker, and reconnects automatically after app restarts.

The helper and its encrypted key are saved privately under `%LOCALAPPDATA%\DigitXBDPrint`. They are separate from your project. Do not upload this folder to GitHub or share the helper key. The encrypted key works only for this Windows account.

## Print a customer's document

1. Open **Files**. Open the PDF first to check the document.
2. Click **Print** beside that file.
3. Choose copies, black-and-white or color, pages and paper size. Blank pages means the entire PDF. Examples: `1-3,5` prints pages 1, 2, 3 and 5.
4. Click **Send to printer**. Follow its progress in **Print queue**.

For mixed documents, send the black-and-white page range as one job and the color range as another. Check the page order before binding. Printing is single-sided; automatic duplex is not enabled. Convert Word documents and photos to PDF before using this feature.

## Understand job status

| Status | What it means |
| --- | --- |
| Waiting | Waiting for the helper. You can cancel it. |
| Sending | The helper is preparing or sending the PDF. |
| Submitted to Windows | Windows accepted the print command. This does not confirm that paper has physically printed. |
| Failed | The document could not be prepared or downloaded. Review before sending again. |
| Check printer | Submission may have happened before an interruption. Check the printer and Windows queue before sending again. |
| Cancelled | A waiting job was cancelled. |

Jobs are never automatically resent after a printing error or interruption. **Review & send again** creates a new job; it can create extra copies if the previous job actually printed. To stop a job already sent, cancel it from the Windows printer queue. Printing does not mark an order delivered and does not create or change invoices.

## Automatic startup

No manual launch is needed after the one-time setup. A shortcut called **DigitXBD Print Connector** in your Windows Startup folder starts the connector at sign-in. The connector waits if Docker is stopped and reconnects when your app becomes available. **Start-DigitXBD.ps1** also starts the installed connector.

If you already set up an older helper, download the latest helper ZIP and run **Install-AutoStart.ps1** from the extracted folder. It uses your saved printer and encrypted key; you do not need to pair again. It replaces the earlier DigitXBD scheduled task with a Startup shortcut.

Windows must be signed in to the account used for setup, and the shop computer must be awake. A Linux Docker container cannot launch a Windows program or use the Canon Windows driver by itself; this connector is installed once on the Windows computer with the printer.

To disable automatic startup, remove **DigitXBD Print Connector** from `Win + R → shell:startup`. Disconnect the helper in the app to cancel waiting jobs and revoke its key. Jobs already sent must be cancelled in the Windows printer queue.

## Troubleshooting

- **Helper offline:** start the helper, check the app address and internet connection, and make sure the owner account is still active.
- **SumatraPDF missing:** run setup again with its correct path. Windows File Explorer can help locate `SumatraPDF.exe`.
- **Printer missing:** install the Canon driver and use exactly the name shown by Windows. Run setup again if the printer name changes.
- **Published app blocked:** the helper needs access to `/api/print-agent/*`. If Cloudflare Access or a challenge protects the whole app, allow these paths through that layer; DigitXBD still requires the private helper token. Do not remove normal application authentication.
- **Need to stop printing:** disconnect the helper from Print queue; waiting jobs are cancelled. Also check Windows for jobs already submitted.
- **Expired upload:** upload the document again. Existing file-retention rules still apply. Temporary helper PDFs are removed after submission; journals store only job IDs and results.
- **Restored backup:** pair the helper again. Restoring a backup cancels pending print jobs to prevent old documents being printed again.

Logs are in `%LOCALAPPDATA%\DigitXBDPrint\helper.log`. Keys and PDF contents are not written to logs. This first version supports one shop helper/printer at a time. The helper does not expose a network port.

