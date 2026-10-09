'use strict';
document.addEventListener('input', event => {
  const modalRoot=event.target.closest('#modal');
  if(modalRoot)$$('.item-group',modalRoot).forEach(group=>{
    const amount=Math.round(Number($('.item-qty',group).value)*Math.round(Number($('.item-price',group).value)*100));
    $('.line-total',group).textContent='Line total: '+money(amount);
  });
});
async function confirmOrder(id) {
  const orders=await api('/api/orders'), o=orders.find(o=>o.id===Number(id));
  if(!o)return;
  let options={}; try { options=JSON.parse(o.options); } catch {}
  modal('Review price · ORD-'+String(o.id).padStart(5,'0'),`<form><div class="notice info">${esc(o.name)} · ${esc(o.phone)}<br>${esc(o.details)}<br>Confirming creates one invoice and uses the customer account for this phone automatically.</div><div class="form-grid">${field('Final reviewed bill (৳)','quote',numeric(o.quote??options.minimum_quote??0),'number','min="0.01" step="0.01" required')}${field('Total production cost (৳; blank if unknown)','cost','','number','min="0" step="0.01"')}${field('Paid now (৳)','paid','0','number','min="0" step="0.01"')}${methodField()}${!o.matched_customer_id&&state.customers.filter(c=>normalizePhone(c.phone)===normalizePhone(o.phone)).length>1?customerField():''}<label class="full">Staff notes<textarea name="staff_notes">${esc(o.staff_notes)}</textarea></label></div><div class="modal-footer"><button class="primary" type="submit">Confirm price & create invoice</button></div></form>`,async data=>{
    const result=await api('/api/orders/'+id+'/confirm','POST',data);
    closeModal();await reload();await navigate();
    modal('Invoice ready',`<div class="notice info">Customer ${esc(result.customer_id)} · ${result.already_confirmed?'This order already had an invoice.':'Price confirmed and invoice created.'}</div><a class="primary" href="${esc(result.invoice_url)}" target="_blank" rel="noopener">Open invoice / Print / PDF ↗</a>`);
  });
}
async function transactionEdit(id) {
  const t=await api('/api/transactions/'+id), invoice=t.kind==='Invoice', refund=t.kind==='Refund';
  let items=[]; try { items=JSON.parse(t.items); } catch {}
  if(invoice && (!items.length || items.reduce((n,i)=>n+(i.cost_amount||0),0)!==t.cost)) items=[{description:t.description||t.category,quantity:1,price:t.bill,cost:t.cost,cost_known:t.cost_known}];
  modal('Edit '+t.kind+' · '+id,`<form><div class="notice info">Balances, collections and profit recalculate after saving. Your before-and-after changes are kept in the audit trail.</div><div class="form-grid">${customerField(t.customer_id)}${field('Date','date',t.date,'date','required')}${field('Invoice / job number','number',t.number)}<label>Category<select name="category">${opt([...new Set([...state.categories,t.category])],t.category)}</select></label>${t.kind!=='Adjustment'?field(invoice?'Paid on this invoice (৳)':refund?'Cash refunded (৳)':'Payment received (৳)','paid',numeric(refund?-t.paid:t.paid),'number','min="0" step="0.01"'):''}<label>Payment method<select name="method">${opt(state.methods,t.method)}</select></label>${!invoice&&t.kind!=='Adjustment'?field('Linked invoice ledger ID (optional for payment)','related_id',t.related_id||'','number','min="1"'):''}${t.kind==='Adjustment'?field('Signed balance adjustment (৳)','amount',numeric(t.bill),'number','step="0.01" required'):refund?field('Sales refund (৳)','amount',numeric(-t.bill),'number','min="0.01" step="0.01" required')+field('Cost reversed (৳)','cost_reversal',numeric(-t.cost),'number','min="0" step="0.01"'):''}${field('Description / reason','description',t.description,'text',invoice?'':'required')}${invoice?field('Due date','due_date',t.due_date||'','date'):''}<label class="full">Notes<textarea name="notes">${esc(t.notes)}</textarea></label></div>${invoice?`<div class="item-line item-head"><span>Description</span><span>Qty</span><span>Price/unit</span><span>Cost/unit</span><span></span></div><div id="invoice-items">${items.map(i=>itemLine({...i,price:numeric(i.price),cost:i.cost_known===false||!t.cost_known?'':numeric(i.cost||0)})).join('')}</div>${btn('item-add','＋ Add item')}`:''}<div class="modal-footer"><button class="primary" type="submit">Save changes</button></div></form>`,async(data,form)=>{
    data.kind=t.kind;
    if(!data.related_id)delete data.related_id;
    if(invoice)data.items=$$('.item-group',form).map(group=>({description:$('.item-desc',group).value,quantity:$('.item-qty',group).value,price:$('.item-price',group).value,cost:$('.item-cost',group).value}));
    await api('/api/transactions/'+id,'PUT',data);closeModal();await reload();await navigate();if(route==='billing')await ledgerView();toast('Record updated; balances recalculated.');
  });
}
async function expenseEdit(id) {
  const entries=await api('/api/expenses'), e=entries.find(e=>e.id===Number(id));if(!e)return;
  modal('Edit expense / capital · '+id,`<form><div class="form-grid">${field('Date','date',e.date,'date','required')}<label>Entry type<select name="kind">${opt(['Expense','Investment','Owner Withdrawal','Stock Purchase'],e.kind)}</select></label>${field('Category','category',e.category)}${field('Amount (৳)','amount',numeric(e.amount),'number','min="0.01" step="0.01" required')}<label>Payment method<select name="method">${opt(state.methods,e.method)}</select></label>${field('Vendor / supplier','vendor',e.vendor)}${field('Description','description',e.description)}<label class="full">Notes<textarea name="notes">${esc(e.notes)}</textarea></label></div><div class="modal-footer"><button class="primary">Save changes</button></div></form>`,async data=>{await api('/api/expenses/'+id,'PUT',data);closeModal();await reload();navigate();toast('Expense/capital updated.');});
}
async function inventoryEdit(id) {
  const data=await api('/api/inventory'), item=data.items.find(i=>i.id===Number(id));if(!item)return;
  modal('Edit material',`<form><div class="form-grid">${field('Material name','name',item.name,'text','required')}${field('Unit','unit',item.unit,'text','required')}${field('Reorder level','reorder',item.reorder,'number','min="0" step="0.001"')}${field('Supplier','supplier',item.supplier)}</div><div class="modal-footer"><button class="primary">Save material</button></div></form>`,async values=>{await api('/api/inventory/'+id,'PUT',values);closeModal();navigate();toast('Material updated.');});
}
async function movementEdit(id) {
  const data=await api('/api/inventory'), move=data.movements.find(m=>m.id===Number(id));if(!move)return;
  modal('Edit stock movement · '+id,`<form><div class="notice info">A linked stock-purchase cash entry updates with this movement. Changes that would make historical stock negative are blocked.</div><div class="form-grid"><label>Material<select name="item_id">${data.items.map(i=>`<option value="${i.id}" ${i.id===move.item_id?'selected':''}>${esc(i.name)}</option>`).join('')}</select></label>${field('Date','date',move.date,'date','required')}<label>Movement type<select name="kind">${opt(['Opening','Purchased','Used'],move.kind)}</select></label>${field('Quantity','quantity',move.quantity,'number','min="0.001" step="0.001" required')}${field('Unit cost (৳)','unit_cost',numeric(move.unit_cost),'number','min="0" step="0.01"')}<label class="full">Notes<textarea name="notes">${esc(move.notes)}</textarea></label></div><div class="modal-footer"><button class="primary">Save movement</button></div></form>`,async values=>{await api('/api/inventory/movement/'+id,'PUT',values);closeModal();await reload();navigate();toast('Stock and linked cash updated.');});
}
async function serviceEdit(id) {
  const s=state.services.find(s=>s.id===Number(id));if(!s)return;
  modal('Edit service price',`<form><div class="form-grid">${field('Name','name',s.name,'text','required')}${field('Unit','unit',s.unit)}${field('Selling price (৳)','price',numeric(s.price),'number','min="0" step="0.01" required')}${field('Known cost (৳)','cost',numeric(s.cost),'number','min="0" step="0.01" required')}</div><div class="modal-footer"><button class="primary">Save service</button></div></form>`,async values=>{await api('/api/services/'+id,'PUT',values);closeModal();await reload();navigate();toast('Service updated.');});
}
document.addEventListener('click',async event=>{
  const el=event.target.closest('[data-action]');if(!el)return;
  try {
    if(el.dataset.action==='order-confirm')await confirmOrder(el.dataset.id);
    else if(el.dataset.action==='transaction-edit')await transactionEdit(el.dataset.id);
    else if(el.dataset.action==='expense-edit')await expenseEdit(el.dataset.id);
    else if(el.dataset.action==='inventory-edit')await inventoryEdit(el.dataset.id);
    else if(el.dataset.action==='movement-edit')await movementEdit(el.dataset.id);
    else if(el.dataset.action==='service-edit')await serviceEdit(el.dataset.id);
    else if(el.dataset.action==='order-details-edit')await orderDetailsEdit(el.dataset.id);
  } catch(error){toast(error.message);}
});

async function orderDetailsEdit(id) {
  const orders=await api('/api/orders'),o=orders.find(o=>o.id===Number(id));if(!o)return;
  let options={};try{options=JSON.parse(o.options);}catch{}
  modal('Edit online order · '+id,`<form><div class="notice info">Order details and its minimum estimate update here. A confirmed invoice keeps its reviewed bill; edit that invoice separately if the final price changes.</div><div class="form-grid">${field('Customer name','name',o.name,'text','required')}${field('Phone','phone',o.phone,'tel','required')}<label>Service<select name="service">${opt(state.categories,o.service)}</select></label>${field('Copies / photo pieces','quantity',o.quantity,'number','min="1" required')}${field('B&W pages per copy','bw_pages',options.bw_pages??(options.color==='Color'?0:options.pages??1),'number','min="0" max="100000"')}${field('Color pages per copy','color_pages',options.color_pages??(options.color==='Color'?options.pages??1:0),'number','min="0" max="100000"')}${field('Paper size','paper',options.paper||'A4')}<label>Binding<select name="binding">${opt(['None','Spiral','Soft cover','Hard cover','Staple'],options.binding||'None')}</select></label><label>Sides<select name="sides">${opt(['Single sided','Double sided'],options.sides||'Single sided')}</select></label>${field('Collection date','deadline',options.deadline||'','date')}<label class="full">Instructions<textarea name="details" required>${esc(o.details)}</textarea></label></div><div class="modal-footer"><button class="primary">Save order details</button></div></form>`,async data=>{await api('/api/orders/'+id+'/details','PUT',data);closeModal();await reload();navigate();toast('Order details updated.');});
}
