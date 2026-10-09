# DigitXBD workflow update

## Online orders and invoices

Submitting an online order automatically registers a new customer using the normalized phone number, or reuses an existing account. Repeated numbers stay on the same ledger; existing ambiguous duplicate accounts require staff selection. Submission itself does not create a sale or invoice.

Open **Online orders → Review price & create invoice**. Check the files and final bill, enter total production cost (leave blank if unknown), any payment received and the payment method, then click **Confirm price & create invoice**. This creates the invoice, updates customer totals and puts the job In Progress. Clicking confirmation again returns the existing invoice. Setting an unbilled order to Quoted with a positive price also confirms and creates its invoice.

The customer’s private tracking page shows the assigned customer ID and a link to the confirmed invoice. New online orders no longer require a separate customer-creation or invoice-entry step. Existing unbilled requests get the same workflow when reviewed.

## Mixed B&W and color documents

The online form has separate B&W and color page-count boxes per copy. The minimum quote is `(B&W pages × ৳3 + color pages × ৳5) × copies + ৳10 binding if selected`. Stamp photos remain ৳5 each, minimum eight. Give the color page numbers in Instructions so the shop knows which pages to print in color.

PDF detection fills the total page count; it does not classify page colors. When color pages are entered, the form allocates the remaining detected pages to B&W unless the customer has manually set B&W pages. Customers may adjust both counts for selected page ranges.

## Dark mode

Use the Dark mode / Light mode button. The preference is saved per browser and applies across the dashboard, public form, tracking page, statements and invoice preview. The initial theme follows the device preference. Printed invoices use light colors.

## Payment and verification QR

Every invoice includes a verification QR that opens its private invoice page. Upload the original merchant QR image in Settings: every invoice uses the exact uploaded image, including fully paid invoices. No string-based generation is needed. Existing decoded configurations remain a compatibility fallback until an image is uploaded. Payment QR scans never record payment automatically; confirm receipts and record them in the ledger.

## WhatsApp statement links

**Dues & reminders → WhatsApp** adds a private account-statement link to the message. Statements show the latest bills, payments and running balance; they do not show internal notes or business costs. A random secret link identifies the statement, not the customer ID. Keep it between the shop and the customer. `{statement_url}` can be placed inside a custom reminder template; otherwise it is appended automatically.

Set a customer-reachable **Public URL** in Settings (your HTTPS domain or appropriate LAN address). A localhost link only opens on the server computer. You still review and send each message yourself in WhatsApp.

## Admin record editing

Owner accounts act as admins. Use **Edit** in the transaction ledger, expenses/capital, materials and stock movements. Customers, opening balances, online order details, saved service prices and production costs also have editing controls. Staff cannot edit financial history or stock records. Admin edits preserve entry IDs and invoice links and save before-and-after details in the audit trail. Monetary totals recalculate from the updated ledger.

Invoice-linked refunds cannot exceed the corrected bill or cost. Customer changes are blocked on invoices with linked payments/refunds. Stock edits cannot make historical quantities negative. A linked stock-purchase expense updates when its movement changes; a linked cash entry retains its Stock Purchase type. Older purchases are linked automatically only when an exact unambiguous match exists; any older ambiguous/unlinked cash record must be corrected separately.

Invoices keep their reviewed amount when order instructions are edited. To change a confirmed price, edit the invoice itself. Investments and owner withdrawals retain their separate accounting treatment.

## Validation

Run `python -m unittest discover -s tests -p test_workflow.py -v`. The suite includes 35 accounting and workflow checks, using temporary databases. The update adds additive database migrations and retains business records and the Docker volume. A source-code upgrade still needs the existing `.env` and volume; do not reinstall into a different volume to update a live business.

## Delete and restore mistakes

Owners have Delete buttons for customers, transactions, expenses/investments/withdrawals, orders, uploaded files, materials, stock movements, saved services and other team accounts. Review the affected records and enter a reason. Delete moves them to the Recycle Bin; totals are recalculated immediately. Open Recycle Bin from Transactions or Settings to restore them.

Deleting a customer includes their ledger and linked orders. Deleting an invoice includes its explicitly linked payments/refunds and reopens its linked online order for review. Deleting an online order keeps its invoice and customer account. Deleting a stock purchase also removes its linked cash entry. Historical stock must remain nonnegative: correct or delete erroneous usage before deleting stock that supports that usage. IDs remain reserved, and restores cannot overwrite later changes. Your own signed-in account and the audit trail are retained.

Files in the Recycle Bin still expire under retention rules. Restoring an expired file restores its metadata, not its deleted bytes. Full backups include unexpired recoverable file bytes. No permanent purge control is exposed.

## Phone use and Transactions

The Transactions tab sits immediately below Online orders. It shows the complete ledger in a spreadsheet-style desktop table with search, type filtering and pagination. Running customer balances use all entries, even while filtered. On phones, each entry becomes a compact card; Show details reveals the extra columns. Forms have labeled stacked items, readable inputs and larger touch controls. Customers are listed by their ID sequence.

The dashboard's dark theme uses black backgrounds, translucent glass panels and high-contrast text. Use your customer-reachable HTTPS/LAN URL on the phone; localhost only works on the server computer. See README for existing deployment configuration.

## Invoice and statement appearance

Verification QR is in the invoice header. The original merchant payment image is displayed exactly as uploaded, preserving its existing branding and proportions. The requested merchant heading and original-QR explanation were removed. Verification QR uses high error correction. Original payment images are neither decoded nor modified. Previous uploaded images can be restored from Settings and all are included in full backups.

Statements use Current due. Unpaid invoice entries have no displayed payment method; historical stored methods remain intact. Fully settled invoices show a PAID watermark (fully refunded invoices are excluded). Due dates are shown only while an amount remains due. The current complete suite is `python -m unittest discover -s tests -p test_records.py -v`, with 49 checks.

## Shop document upload
Customers visiting the shop use /order to upload files with their name and mobile number. The phone number reuses an existing customer account. No invoice or quote is created. Staff open the Files tab, search by customer or filename, open PDFs in the browser, download other files, and create the invoice manually in Counter & billing. All documents are stored privately in the persistent /data/uploads folder. Shop files expire the configured number of days after upload; online order files keep the configured retention basis. Online ordering is now at /online_order. Files includes a shop upload QR and link; Online orders keeps its own order QR. Existing tracking links and invoices keep working.
