/* Owner controls: review dependencies, delete reversibly, and restore. */
const deleteButton=(kind,id)=>state.role==='owner'?btn('record-delete','Delete','danger-button',`data-kind="${kind}" data-id="${esc(id)}"`):'';
async function deleteRecord(kind,id){
  const preview=await api('/api/delete-preview/'+kind+'/'+encodeURIComponent(id));
  closeModal();
  modal('Delete · '+esc(preview.label),`<form><p>This moves the following records to the Recycle Bin and recalculates totals. You can restore them later.</p><ul>${Object.entries(preview.counts).map(([t,n])=>`<li>${n} ${esc(t==='ledger'?'transactions':t)}</li>`).join('')}</ul>${preview.reopened_orders?`<div class="notice">${preview.reopened_orders} linked order will return to New for a fresh price review.</div>`:''}${kind==='orders'?'<p>The customer account and any confirmed invoice remain in their own tabs.</p>':''}${field('Reason','reason','','text','required maxlength="500" placeholder="For example: duplicate entry"')}<div class="modal-footer">${btn('close-modal','Cancel')}<button type="submit" class="danger-button">Delete these records</button></div></form>`,async data=>{
    await api('/api/records/'+kind+'/'+encodeURIComponent(id),'DELETE',{...data,fingerprint:preview.fingerprint});
    closeModal();await reload();await navigate();toast('Moved to Recycle Bin. Totals updated.');
  });
}
async function recycleBin(){
  const records=await api('/api/recycle-bin');closeModal();
  modal('Recycle Bin',`<p>Restore deleted records and their original links. Files remain subject to the retention period. Audit history stays available.</p>${records.length?`<div class="modal-footer">${btn('recycle-clear','Clear recycle bin','danger-button')}</div>`:''}${table(['Deleted','Record','Reason','By',''],records.map(r=>`<tr><td>${esc(r.created.slice(0,10))}</td><td>${esc(r.label)}<small>${esc(r.kind)} · ${esc(r.record_id)}</small></td><td>${esc(r.reason)}</td><td>${esc(r.actor)}</td><td>${btn('record-restore','Restore','secondary',`data-id="${r.id}"`)}</td></tr>`).join(''),'No deleted records.')}`);
  mobileTables($('#modal'));
}
function mobileTables(root=document){
  $$('table',root).forEach(t=>{
    if(t.closest('.react-screen'))return;
    const headers=$$('thead th',t).map(h=>h.textContent);
    $$('tbody tr',t).forEach(row=>$$('td',row).forEach((td,i)=>{td.dataset.label=headers[i]||'Actions';}));
    if(t.closest('.transactions-panel'))$$('tbody tr',t).forEach(row=>{
      if(!row.querySelector('.transaction-details-toggle')&&row.children.length>1){
        const toggle=document.createElement('button');toggle.type='button';toggle.className='secondary transaction-details-toggle';toggle.textContent='Show details';toggle.setAttribute('aria-expanded','false');
        toggle.addEventListener('click',()=>{const expanded=row.classList.toggle('expanded');toggle.textContent=expanded?'Less detail':'Show details';toggle.setAttribute('aria-expanded',String(expanded));});row.lastElementChild.append(toggle);
      }
    });
  });
  $$('.item-line:not(.item-head)',root).forEach(line=>{
    $$('input',line).forEach(input=>{
      if(input.parentElement.tagName==='LABEL')return;
      const name=input.classList.contains('item-desc')?'Description':input.classList.contains('item-qty')?'Quantity':input.classList.contains('item-price')?'Unit price (৳)':'Cost per unit (৳)';
      const label=document.createElement('label');label.className='mobile-item-label';
      const span=document.createElement('span');span.textContent=name;label.append(span);
      input.replaceWith(label);label.append(input);
    });
  });
}
new MutationObserver(()=>mobileTables()).observe($('#content'),{childList:true,subtree:true});
new MutationObserver(()=>mobileTables($('#modal'))).observe($('#modal-content'),{childList:true,subtree:true});
document.addEventListener('click',async e=>{
  const el=e.target.closest('[data-action]');if(!el)return;
  try{
    if(el.dataset.action==='record-delete')await deleteRecord(el.dataset.kind,el.dataset.id);
    if(el.dataset.action==='recycle-bin')await recycleBin();
    if(el.dataset.action==='recycle-clear'){
      const preview=await api('/api/recycle-bin/clear-preview');closeModal();
      modal('Clear recycle bin',`<form><p class="notice danger">Permanently remove ${preview.count} deleted item(s), their archived records and unused uploaded files. These items can no longer be restored from this app.</p><p>Active records, restored records and audit history are kept.</p>${field('Type CLEAR to confirm','confirmation','','text','required pattern="CLEAR" autocomplete="off"')}<div class="modal-footer">${btn('close-modal','Cancel')}<button type="submit" class="danger-button">Permanently clear recycle bin</button></div></form>`,async values=>{await api('/api/recycle-bin/clear','POST',{...values,fingerprint:preview.fingerprint});closeModal();await recycleBin();toast('Recycle bin cleared.');});
    }
    if(el.dataset.action==='record-restore'){
      el.disabled=true;await api('/api/recycle-bin/'+el.dataset.id+'/restore','POST',{});
      closeModal();await reload();await navigate();await recycleBin();toast('Record restored. Totals updated.');
    }
    if(el.dataset.action==='merchant-image-remove'){
      closeModal();modal('Remove merchant QR image',`<p>The invoice payment image will be removed. You can restore it from Previous images in Settings.</p><div class="modal-footer">${btn('close-modal','Cancel')}${btn('merchant-image-remove-confirm','Remove image','danger-button')}</div>`);
    }
    if(el.dataset.action==='merchant-image-remove-confirm'){
      await api('/api/merchant-qr','DELETE',{});closeModal();await reload();await navigate();toast('Merchant image removed. Previous images remain available.');
    }
    if(el.dataset.action==='merchant-image-history'){
      const images=await api('/api/merchant-qr/history');closeModal();modal('Previous merchant QR images',table(['Uploaded','Image',''],images.map(i=>`<tr><td>${esc(i.created.slice(0,10))}</td><td>${esc(i.name)}</td><td>${btn('merchant-image-restore','Use this image','secondary',`data-id="${i.id}"`)}</td></tr>`).join(''),'No images uploaded yet.'));mobileTables($('#modal'));
    }
    if(el.dataset.action==='merchant-image-restore'){
      await api('/api/merchant-qr/'+el.dataset.id+'/restore','POST',{});closeModal();await reload();await navigate();toast('Previous merchant image restored.');
    }
  }catch(error){toast(error.message);el.disabled=false;}
});
