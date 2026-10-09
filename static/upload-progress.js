'use strict';
window.DigitXUpload={
  send(path,form){
    let progress=form.querySelector('.upload-progress');
    if(!progress){
      progress=document.createElement('div');progress.className='upload-progress hidden';
      progress.innerHTML='<div class="upload-ring" role="progressbar" aria-label="Document upload" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0"><svg viewBox="0 0 100 100" aria-hidden="true"><circle class="upload-ring-track" cx="50" cy="50" r="43"/><circle class="upload-ring-value" cx="50" cy="50" r="43"/></svg><strong>0%</strong></div><div><b class="upload-progress-title">Uploading your documents</b><p class="upload-progress-note" role="status">Keep this page open.</p></div>';
      form.querySelector('button[type=submit]').before(progress);
    }
    progress.classList.remove('hidden','upload-finishing');form.setAttribute('aria-busy','true');
    const ring=progress.querySelector('.upload-ring'),circle=progress.querySelector('.upload-ring-value'),number=progress.querySelector('strong'),title=progress.querySelector('.upload-progress-title'),note=progress.querySelector('.upload-progress-note');
    const update=value=>{ring.setAttribute('aria-valuenow',String(value));circle.style.strokeDashoffset=String(270.18*(1-value/100));number.textContent=value+'%';};
    update(0);title.textContent='Uploading your documents';note.textContent='Keep this page open.';
    return new Promise((resolve,reject)=>{
      const xhr=new XMLHttpRequest();xhr.open('POST',path);xhr.responseType='json';
      xhr.upload.onprogress=event=>{if(event.lengthComputable)update(Math.floor(event.loaded/event.total*100));};
      xhr.upload.onload=()=>{update(100);progress.classList.add('upload-finishing');title.textContent='Upload complete';note.textContent='Finishing your request… Please keep this page open.';};
      const finish=()=>{form.removeAttribute('aria-busy');progress.classList.add('hidden');};
      xhr.onload=()=>{finish();const data=xhr.response;if(xhr.status>=200&&xhr.status<300&&data)resolve(data);else reject(new Error(data?.error||(xhr.status===413?'This upload was rejected by the connection provider. Try sending smaller groups of files or contact the shop.':'Could not finish your upload. Please try again.')));};
      xhr.onerror=()=>{finish();reject(new Error('Connection lost during upload. Check your internet connection and try again.'));};
      xhr.onabort=()=>{finish();reject(new Error('Upload cancelled.'));};
      xhr.send(new FormData(form));
    });
  }
};
