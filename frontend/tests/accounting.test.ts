import test from 'node:test';
import assert from 'node:assert/strict';
import {invoiceTotals,lineAmount,paisa,normalizePhone} from '../src/accounting.ts';
test('later collection does not change job profit',()=>{
 const items=[{description:'Printing',quantity:'1',price:'1000',cost:'400'}];
 assert.deepEqual(invoiceTotals(items,'600'),{bill:100000,cost:40000,profit:60000,due:40000,known:true});
 assert.equal(invoiceTotals(items,'1000').profit,60000);
});
test('fractional quantities and half-paisa match server rounding',()=>{
 assert.equal(paisa('1.005'),101);assert.equal(lineAmount('0.5','0.01'),1);
 assert.equal(lineAmount('1.125','3.25'),366);
});
test('unknown production cost stays provisional',()=>{
 assert.equal(invoiceTotals([{description:'Print',quantity:'3',price:'5',cost:''}],'0').known,false);
 assert.equal(invoiceTotals([{description:'Print',quantity:'3',price:'5',cost:'0'}],'0').known,true);
});
test('Bangladesh phone formats resolve to the same customer',()=>{
 for(const p of ['01712345678','+8801712345678','008801712345678'])assert.equal(normalizePhone(p),'8801712345678');
});
