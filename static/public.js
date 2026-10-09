const form = document.querySelector('#order-form');
if (form) {
  const prices = JSON.parse(document.querySelector('#order-prices').textContent);
  const field = name => form.elements.namedItem(name);
  const money = amount => '৳' + amount.toLocaleString('en-BD');
  let analysisVersion = 0, analyzing = false, detectedTotal = null, bwManual = false;
  let lookupTimer, lookupVersion = 0;
  field('phone').addEventListener('input', () => {
    clearTimeout(lookupTimer);
    const version = ++lookupVersion, status = document.querySelector('#customer-match');
    const number = field('phone').value.replace(/\D/g, '').replace(/^01/, '8801');
    status.textContent = 'Use the same number for repeat orders.';
    if (!/^8801\d{9}$/.test(number)) return;
    lookupTimer = setTimeout(async () => {
      status.textContent = 'Checking customer ID…';
      try {
        const response = await fetch('/order/customer', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': field('csrf').value}, body: JSON.stringify({phone: number})});
        const data = await response.json();
        if (version !== lookupVersion) return;
        if (!response.ok) throw new Error(data.error);
        status.textContent = data.customer_id ? 'Welcome back · Customer ID: ' + data.customer_id : data.multiple ? 'Multiple accounts found. The shop will confirm your customer ID.' : 'New number · Your customer ID will be created automatically when you submit.';
      } catch (error) { if (version === lookupVersion) status.textContent = error.message || 'The shop will match your customer account.'; }
    }, 500);
  });
  function quote(serviceChanged = false) {
    const service = field('service').value, stamp = service === 'Stamp Size Photo';
    const custom = ['Photo Printing','Lamination','Other'].includes(service), bindingOnly = service === 'Binding';
    field('quantity').min = stamp ? prices.stamp_min : 1;
    if (serviceChanged && stamp && Number(field('quantity').value) < prices.stamp_min) field('quantity').value = prices.stamp_min;
    document.querySelector('#quantity-label').textContent = stamp ? 'Number of photos (minimum 8)' : 'Number of copies';
    for (const id of ['bw-label','color-pages-label','paper-label','sides-label']) document.getElementById(id).hidden = stamp || bindingOnly;
    field('bw_pages').required = field('color_pages').required = !stamp && !bindingOnly;
    if (serviceChanged && ['Color Printing','Black & White Printing'].includes(service)) {
      const total = Number(field('bw_pages').value) + Number(field('color_pages').value) || 1;
      field('bw_pages').value = service === 'Color Printing' ? 0 : total;
      field('color_pages').value = service === 'Color Printing' ? total : 0;
    }
    const qty = Number(field('quantity').value), bw = Number(field('bw_pages').value), color = Number(field('color_pages').value);
    const binding = field('binding').value !== 'None' ? prices.binding : 0;
    let amount, breakdown;
    if (custom) { amount = null; breakdown = 'The shop will quote this service after reviewing your request.'; }
    else if (bindingOnly) { amount = prices.binding; breakdown = 'Binding starts at '+money(prices.binding)+' per order'; }
    else if (stamp) { amount = qty * prices.stamp + binding; breakdown = qty+' photos × '+money(prices.stamp)+(qty < prices.stamp_min ? ' · minimum 8 required' : ''); }
    else { amount = qty * (bw * prices.bw + color * prices.color) + binding; breakdown = bw+' B&W × '+money(prices.bw)+' + '+color+' color × '+money(prices.color)+' · '+qty+' copies'; }
    if (binding && !custom && !bindingOnly) breakdown += ' + '+money(binding)+' binding';
    document.querySelector('#quote-total').textContent = amount === null ? 'Quote needed' : money(amount);
    document.querySelector('#quote-breakdown').textContent = breakdown;
    field('bw_pages').setCustomValidity(!stamp && !bindingOnly && !custom && bw + color < 1 ? 'Enter at least one printed page.' : '');
  }
  field('bw_pages').addEventListener('input', () => { bwManual = true; });
  field('color_pages').addEventListener('input', () => { if (detectedTotal !== null && !bwManual) field('bw_pages').value = Math.max(0, detectedTotal - Number(field('color_pages').value)); });
  form.addEventListener('input', () => quote());
  field('service').addEventListener('change', () => quote(true));
  field('files').addEventListener('change', async () => {
    const version = ++analysisVersion, status = document.querySelector('#page-detection'), files = [...field('files').files];
    if (!files.length) { detectedTotal = null; bwManual = false; analyzing = false; status.textContent = 'No files selected. Enter the page count manually.'; return; }
    if (files.length > 5) { analyzing = false; status.textContent = 'Select up to 5 files.'; return; }
    detectedTotal = null; bwManual = false; analyzing = true; status.textContent = 'Counting pages…';
    const data = new FormData(); data.append('csrf', field('csrf').value); files.forEach(f => data.append('files', f));
    try {
      const response = await fetch('/order/analyze', {method: 'POST', body: data}), result = await response.json();
      if (version !== analysisVersion) return;
      if (!response.ok) throw new Error(result.error || 'Could not count pages.');
      if (result.complete) { detectedTotal = result.total_pages; field('bw_pages').value = field('service').value === 'Color Printing' ? 0 : detectedTotal; field('color_pages').value = field('service').value === 'Color Printing' ? detectedTotal : 0; }
      status.textContent = result.files.map(f => f.name + ': ' + (f.pages === null ? 'manual count needed' : f.pages + ' page(s)')).join(' · ') + (result.complete ? '. Total counted. Choose how many pages are color; remaining pages are B&W. Color detection is manual.' : '. Enter the combined count for all files manually.');
      quote();
    } catch (error) { if (version === analysisVersion) status.textContent = error.message + ' Enter the page count manually.'; }
    finally { if (version === analysisVersion) analyzing = false; }
  });
  quote();
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const button = form.querySelector('button[type=submit]'), error = document.querySelector('#form-error');
    if (analyzing) { error.textContent = 'Please wait for page counting to finish.'; error.classList.remove('hidden'); return; }
    button.disabled = true; button.textContent = 'Uploading your order…'; error.classList.add('hidden');
    try {
      const data = await window.DigitXUpload.send('/online_order', form);

      location.assign(data.tracking_url);
    } catch (e) { error.textContent = e.message; error.classList.remove('hidden'); button.disabled = false; button.textContent = 'Submit order →'; }
  });
}
