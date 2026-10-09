export interface Item {description:string; quantity:string; price:string; cost:string;}
export const emptyItem=():Item=>({description:'',quantity:'1',price:'',cost:''});
// Match the server's positive Decimal ROUND_HALF_UP without floating-point money.
function decimal(value:string){
  if(!/^\d*(\.\d*)?$/.test(value))return {value:0n,scale:1n};
  const [whole='',fraction='']=value.split('.');
  return {value:BigInt((whole||'0')+fraction),scale:10n**BigInt(fraction.length)};
}
function round(n:bigint,d:bigint){return Number((n*2n+d)/(d*2n));}
export function paisa(value:string){const parsed=decimal(value);return round(parsed.value*100n,parsed.scale);}
export function lineAmount(quantity:string,price:string){const q=decimal(quantity);return round(q.value*BigInt(paisa(price)),q.scale);}
export function invoiceTotals(items:Item[],paid:string){
  const bill=items.reduce((n,i)=>n+lineAmount(i.quantity,i.price),0);
  const cost=items.reduce((n,i)=>n+lineAmount(i.quantity,i.cost),0);
  return {bill,cost,profit:bill-cost,due:bill-paisa(paid),known:items.every(i=>i.cost.trim()!=='')};
}
export function normalizePhone(value:string){return value.replace(/\D/g,'').replace(/^00880/,'880').replace(/^01/,'8801');}
