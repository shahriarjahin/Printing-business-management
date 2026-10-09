'use strict';
const printLabels={queued:'Waiting',claimed:'Sending',submitted:'Submitted to Windows',failed:'Failed',cancelled:'Cancelled',uncertain:'Check printer'};
async function printingView(){
 const data=await api('/api/printing');if(route!=='printing')return;
 const a=data.agent;
 const headers=['Job','Document','Print options','Status','Actions'];
 const body=data.jobs.map(j=>{const o=j.options;const color=j.status==='submitted'?'green':j.status==='failed'||j.status==='uncertain'?'red':'blue';const cells=[`#${j.id}<small>${esc(j.created)}</small>`,esc(j.file_name)+`<small>${esc(j.customer)}</small>`,`${o.copies} copies · ${esc(o.mode==='color'?'Color':'Black & white')}<small>${esc(o.paper)} · ${esc(o.pages||'All pages')} · ${esc(o.printer)}</small>`,badge(printLabels[j.status],color)+`<small>${esc(j.detail)}</small>`,j.status==='queued'?btn('print-cancel','Cancel','secondary',`data-id="${j.id}"`):(j.status==='failed'||j.status==='uncertain'?btn('print-file','Review & send again','secondary',`data-id="${j.file_id}" data-review="1"`):'')];return '<tr>'+cells.map((c,i)=>`<td data-label="${headers[i]}">${c}</td>`).join('')+'</tr>';}).join('');
 $('#content').innerHTML=head('Print queue','Review PDFs and send them to your shop printer. Printing never creates a bill.',btn('print-refresh','Refresh')+'<a class="secondary" href="#files">Browse files</a>')+`<section class="panel"><div class="panel-head"><h2>Shop printer</h2>${badge(a.online?'Connected':a.paired?'Helper offline':'Setup needed',a.online?'green':'orange')}</div><p>${esc(a.printer||'Connect the Windows helper on the computer with your Canon printer.')}</p><p class="notice">Submitted means Windows accepted the job. Check the printer for paper, ink and completion. Interrupted jobs are never resent automatically.</p><div class="head-actions"><a class="secondary" href="/api/printing/helper.zip">Download Windows helper</a>${btn('print-pair',a.paired?'Replace helper key':'Connect printer helper')}${a.paired?btn('print-disconnect','Disconnect helper'):''}</div><p><small>Install SumatraPDF, extract the helper, and run Setup-Printer.ps1. One-time setup enables automatic startup at Windows sign-in and automatic reconnect when Docker starts. Setup instructions are included in the download.</small></p></section><section class="panel printing-panel"><div class="panel-head"><h2>Recent print jobs</h2><small>Latest 200</small></div>${table(headers,body,'No print jobs yet. Open Files and choose Print beside a PDF.')}</section>`;
}
async function printFile(fid,review=false){
 const data=await api('/api/printing');const a=data.agent;
 if(!a.paired||!a.printer){location.hash='printing';toast('Connect the Windows helper first.');return;}
 const requestKey=crypto.randomUUID();
 modal('Print PDF',`<form><p>Printer: <b>${esc(a.printer)}</b></p>${review?'<p class="notice danger">Check the physical printer and Windows queue first. Sending again can produce duplicate copies.</p>':''}${!a.online?'<p class="notice">Helper is offline. This job will wait until it reconnects.</p>':''}<div class="form-grid">${field('Copies','copies','1','number','min="1" max="50" required')}<label>Color mode<select name="mode"><option value="monochrome">Black & white</option><option value="color">Color</option></select></label>${field('Pages (blank = all)','pages','','text','placeholder="1-3,5,8-10" maxlength="300"')}<label>Paper size<select name="paper">${opt(['A4','A5','letter','legal'],'A4')}</select></label><label>Page sizing<select name="scale"><option value="fit">Fit to paper</option><option value="shrink">Shrink large pages</option><option value="noscale">Actual size</option></select></label></div><p><small>Single-sided printing. For mixed documents, send the black-and-white and color page ranges as separate jobs. Check page order before binding.</small></p><div class="modal-footer"><button type="submit" class="primary">Send to printer</button></div></form>`,async values=>{await api('/api/printing/jobs','POST',{...values,file_id:Number(fid),request_key:requestKey});closeModal();toast('Print job queued.');location.hash='printing';if(route==='printing')await printingView();});
}
document.addEventListener('click',async event=>{
 const button=event.target.closest('[data-action]');if(!button)return;
 try{
  const action=button.dataset.action;
  if(action==='print-file')await printFile(button.dataset.id,!!button.dataset.review);
  if(action==='print-refresh')await printingView();
  if(action==='print-cancel'){await api(`/api/printing/jobs/${button.dataset.id}/cancel`,'POST',{});await printingView();}
  if(action==='print-pair'){
   modal('Connect Windows printer',`<form><p>Download and extract the Windows helper first. Generate a key, then paste it into Setup-Printer.ps1 on the shop computer.</p><p class="notice">Replacing a key disconnects the previous helper. Check any jobs currently sending before replacing it.</p><button class="primary" type="submit">Generate helper key</button></form>`,async()=>{
    const result=await api('/api/printing/pair','POST',{});closeModal();
    modal('Your printer helper key',`<p>This key is shown once. It allows access to documents approved for printing. Keep it private.</p><label>Helper key<input readonly id="printer-pair-key" value="${esc(result.token)}" autocomplete="off"></label>${btn('print-copy-key','Copy key')}<p>Run Setup-Printer.ps1 on your Windows shop computer. Enter your app address and this key when asked.</p>`);
   });
  }
  if(action==='print-copy-key'){await navigator.clipboard.writeText($('#printer-pair-key').value);toast('Helper key copied.');}
  if(action==='print-disconnect')modal('Disconnect printer helper',`<form><p>Waiting jobs will be cancelled. Sending jobs must be checked at the printer.</p><button type="submit" class="primary">Disconnect</button></form>`,async()=>{await api('/api/printing/disconnect','POST',{});closeModal();await printingView();});
 }catch(error){toast(error.message);}
});
setInterval(()=>{if(route==='printing'&&!$('#modal').open)printingView().catch(()=>{});},10000);
