const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const nodes={};
for(const name of ['.upload-ring','.upload-ring-value','strong','.upload-progress-title','.upload-progress-note'])nodes[name]={style:{},textContent:'',attributes:{},setAttribute(k,v){this.attributes[k]=v;}};
const classes=new Set(['hidden']);
const panel={classList:{add(...names){names.forEach(n=>classes.add(n));},remove(...names){names.forEach(n=>classes.delete(n));}},querySelector(name){return nodes[name];},innerHTML:''};
const form={busy:false,querySelector(name){return name==='.upload-progress'?panel:null;},setAttribute(){this.busy=true;},removeAttribute(){this.busy=false;}};
let xhr;
class FakeXHR{constructor(){xhr=this;this.upload={};}open(method,path){this.method=method;this.path=path;}send(body){this.body=body;}}
const context={window:{},document:{createElement(){return panel;}},XMLHttpRequest:FakeXHR,FormData:class{constructor(value){this.form=value;}},Promise,Error};
vm.runInNewContext(fs.readFileSync('static/upload-progress.js','utf8'),context);
(async()=>{
 const request=context.window.DigitXUpload.send('/order',form);
 assert.equal(classes.has('hidden'),false);assert.equal(form.busy,true);
 xhr.upload.onprogress({lengthComputable:true,loaded:42,total:100});
 assert.equal(nodes.strong.textContent,'42%');assert.equal(nodes['.upload-ring'].attributes['aria-valuenow'],'42');
 assert.ok(Math.abs(Number(nodes['.upload-ring-value'].style.strokeDashoffset)-156.7044)<0.001);
 xhr.upload.onload();assert.equal(nodes.strong.textContent,'100%');assert.ok(classes.has('upload-finishing'));
 assert.equal(form.busy,true); // Transfer completion alone does not mean the order was saved.
 xhr.status=201;xhr.response={order_number:'TEST'};xhr.onload();
 assert.equal((await request).order_number,'TEST');assert.equal(form.busy,false);assert.ok(classes.has('hidden'));
 const failed=context.window.DigitXUpload.send('/online_order',form);xhr.onerror();
 await assert.rejects(failed,/Connection lost/);assert.equal(form.busy,false);
 console.log('Upload progress passed: real percentage, server-processing phase and network-error recovery.');
})().catch(error=>{console.error(error);process.exitCode=1;});
