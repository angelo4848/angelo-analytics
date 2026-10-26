(function(){
var STOP=/\b(fc|sc|cf|ac|cd|ca|club|de|del|la|el|the|sk|fk|afc|united|utd|city|real|atletico|sporting|deportivo|san|santa|universidad|sport|super|giant)\b/g;
function norm(s){return String(s).normalize('NFD').replace(/[̀-ͯ]/g,'').toLowerCase().replace(/[^a-z0-9 ]/g,' ').replace(STOP,' ').replace(/\s+/g,' ').trim()}
function toks(s){return norm(s).split(' ').filter(function(w){return w.length>2})}
function sim(a,b){var A=toks(a),B=toks(b);return A.some(function(x){return B.some(function(y){return x===y||(x.length>3&&y.length>3&&(x.indexOf(y)===0||y.indexOf(x)===0))})})}
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]})}
var EV=[],OPEN=null;

var css=document.createElement('style');css.textContent=
'.mrow{cursor:pointer}'+
'#sheet{position:fixed;inset:0;z-index:30;background:rgba(5,12,26,.72);display:flex;align-items:flex-end;justify-content:center}'+
'#sheet .box{width:100%;max-width:560px;max-height:88%;overflow:auto;background:var(--navy-2);border:1px solid var(--line);border-bottom:0;border-radius:22px 22px 0 0;padding:18px max(18px,env(safe-area-inset-right,0px)) calc(22px + env(safe-area-inset-bottom,0px)) max(18px,env(safe-area-inset-left,0px))}'+
'#sheet .bar{display:flex;justify-content:space-between;align-items:center;gap:10px;color:var(--mute);font-size:12px;letter-spacing:.08em;text-transform:uppercase;font-weight:700}'+
'#sheet .x{background:none;border:1px solid var(--line);color:var(--ink);border-radius:10px;padding:6px 12px;font:600 13px var(--body);cursor:pointer}'+
'#sheet .board{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:10px;margin:18px 0 6px;text-align:center}'+
'#sheet .tm{font-weight:700;font-size:16px;min-width:0}'+
'#sheet .big{font-family:var(--display);font-weight:800;font-size:56px;line-height:1;font-variant-numeric:tabular-nums}'+
'#sheet .stt{text-align:center;font-weight:800;font-size:13px;letter-spacing:.08em}'+
'#sheet h4{font-family:var(--display);font-size:20px;margin:22px 0 8px;letter-spacing:.03em}'+
'#sheet .ev{display:grid;grid-template-columns:1fr 46px 1fr;gap:8px;align-items:center;padding:7px 0;border-bottom:1px dashed var(--line);font-size:14px}'+
'#sheet .ev .min{text-align:center;font-family:var(--display);font-weight:700;color:var(--mute)}'+
'#sheet .ev .r{text-align:left}#sheet .ev .l{text-align:right}'+
'#sheet .ic{display:inline-block;width:10px;height:13px;border-radius:2px;vertical-align:-1px;margin:0 6px}'+
'#sheet .ic.g{width:10px;height:10px;border-radius:99px;background:var(--win)}#sheet .ic.y{background:#facc15}#sheet .ic.rd{background:var(--loss)}'+
'#sheet .st{margin:10px 0}#sheet .st .lb{display:flex;justify-content:space-between;font-size:13px;color:var(--soft);font-variant-numeric:tabular-nums}'+
'#sheet .st .tr{display:flex;gap:4px;height:6px;margin-top:5px}#sheet .st .tr i{display:block;border-radius:3px}'+
'#sheet .note2{color:var(--mute);font-size:13px;margin-top:16px}'+
'#sheet .tend2{margin-top:14px;background:rgba(34,197,94,.08);border:1px solid rgba(34,197,94,.3);border-radius:14px;padding:12px 14px;font-size:14px}';
document.head.appendChild(css);

function today(){var d=new Date();return d.getFullYear()+String(d.getMonth()+1).padStart(2,'0')+String(d.getDate()).padStart(2,'0')}
function load(){
  fetch('https://site.api.espn.com/apis/site/v2/sports/soccer/all/scoreboard?dates='+today()).then(function(r){return r.json()}).then(function(j){
    EV=(j.events||[]).map(function(e){var c=e.competitions[0],cs=c.competitors;
      var h=cs.filter(function(x){return x.homeAway==='home'})[0]||cs[0],a=cs.filter(function(x){return x.homeAway==='away'})[0]||cs[1];
      function stats(x){var o={};(x.statistics||[]).forEach(function(s){o[s.name]=parseFloat(s.displayValue)});return o}
      return {h:h.team.displayName,a:a.team.displayName,hid:h.team.id,hs:h.score,as:a.score,st:e.status.type.state,det:e.status.type.shortDetail||'',
        details:(c.details||[]).map(function(d){return {t:(d.type&&d.type.text)||'',min:(d.clock&&d.clock.displayValue)||'',team:d.team&&d.team.id,who:(d.athletesInvolved||[]).map(function(p){return p.displayName}).join(', ')}}),
        sh:stats(h),sa:stats(a)}});
    apply();if(OPEN)drawSheet();
  }).catch(function(){});
}
function find(h,a){return EV.filter(function(e){return sim(e.h,h)&&sim(e.a,a)})[0]}
function stLabel(ev){if(ev.st==='in')return /HT|Half/i.test(ev.det)?'DESCANSO':ev.det;if(ev.st==='post')return 'FINAL';return ''}
function apply(){
  document.querySelectorAll('.mrow').forEach(function(row){
    var t=row.querySelector('.teams');if(!t||!t.firstChild)return;
    var p=t.firstChild.textContent.split(' – ');if(p.length<2)return;
    var tmb=row.querySelector('.time');if(tmb&&tmb.firstChild&&tmb.firstChild.nodeType===3&&tmb.firstChild.textContent==='00:00')tmb.firstChild.textContent='';
    var link=row.querySelector('.side a');if(link&&link.textContent.indexOf('Ver partido')<0){link.textContent='Ver partido ›';link.removeAttribute('href');link.removeAttribute('target');link.setAttribute('role','button')}
    var ev=find(p[0],p[1]);
    if(!ev||ev.st==='pre')return;
    var side=row.querySelector('.side'),sc=side.querySelector('.score');
    if(!sc){sc=document.createElement('span');sc.className='score';side.insertBefore(sc,side.firstChild)}
    var v=ev.hs+' - '+ev.as;if(sc.textContent!==v)sc.textContent=v;
    var tm=row.querySelector('.time small');
    if(ev.st==='in'){row.classList.add('live');if(tm){tm.className='st-live';tm.innerHTML='<span class="blink"></span>'+esc(stLabel(ev))}}
    else if(ev.st==='post'){row.classList.remove('live');if(tm){tm.className='st-end';tm.textContent='FINAL'}}
  });
}
function icon(t){t=t.toLowerCase();if(t.indexOf('goal')>=0||t.indexOf('scored')>=0)return '<span class="ic g"></span>';if(t.indexOf('red')>=0)return '<span class="ic rd"></span>';if(t.indexOf('yellow')>=0)return '<span class="ic y"></span>';return ''}
function label(t){t=t.toLowerCase();if(t.indexOf('own goal')>=0)return 'Gol en propia';if(t.indexOf('penalty')>=0&&t.indexOf('scored')>=0)return 'Gol de penalti';if(t.indexOf('goal')>=0)return 'Gol';if(t.indexOf('red')>=0)return 'Roja';if(t.indexOf('yellow')>=0)return 'Amarilla';return ''}
function bar(name,h,a,pct){if(isNaN(h)||isNaN(a))return '';var tot=h+a||1;var hp=Math.round(h/tot*100);
  return '<div class="st"><div class="lb"><b>'+(pct?Math.round(h)+'%':h)+'</b><span>'+name+'</span><b>'+(pct?Math.round(a)+'%':a)+'</b></div><div class="tr"><i style="flex:'+hp+';background:var(--win)"></i><i style="flex:'+(100-hp)+';background:var(--mute)"></i></div></div>'}
function drawSheet(){
  var o=OPEN,ev=find(o.h,o.a),s=document.getElementById('sheet');if(!s)return;
  var html='<div class="box" role="dialog" aria-label="Detalle del partido"><div class="bar"><span>'+esc(o.lg)+'</span><button class="x" id="sheetX">Cerrar</button></div>';
  if(ev&&ev.st!=='pre'){
    var live=ev.st==='in';
    html+='<div class="board"><div class="tm">'+esc(o.h)+'</div><div class="big">'+esc(ev.hs)+' - '+esc(ev.as)+'</div><div class="tm">'+esc(o.a)+'</div></div>';
    html+='<div class="stt" style="color:'+(live?'var(--live)':'var(--mute)')+'">'+(live?'<span class="blink"></span>':'')+esc(stLabel(ev))+'</div>';
    var evs=ev.details.filter(function(d){return label(d.t)});
    html+='<h4>Incidencias</h4>';
    if(evs.length){evs.forEach(function(d){var home=d.team===ev.hid;var txt=icon(d.t)+esc(d.who||label(d.t))+' <span style="color:var(--mute)">'+label(d.t)+'</span>';
      html+='<div class="ev"><div class="l">'+(home?txt:'')+'</div><div class="min">'+esc(d.min)+'</div><div class="r">'+(home?'':txt)+'</div></div>'})}
    else html+='<div class="note2" style="margin-top:0">Sin goles ni tarjetas por ahora.</div>';
    var H=ev.sh,A=ev.sa;
    var sb=bar('Posesión',H.possessionPct,A.possessionPct,true)+bar('Tiros',H.totalShots,A.totalShots)+bar('Tiros a puerta',H.shotsOnTarget,A.shotsOnTarget)+bar('Córners',H.wonCorners,A.wonCorners)+bar('Faltas',H.foulsCommitted,A.foulsCommitted);
    if(sb)html+='<h4>Estadísticas</h4>'+sb;
    if(live)html+='<div class="note2">Se actualiza solo cada minuto.</div>';
  }else{
    html+='<div class="board"><div class="tm">'+esc(o.h)+'</div><div class="big" style="font-size:40px">'+esc(o.score||o.time||'vs')+'</div><div class="tm">'+esc(o.a)+'</div></div>';
    html+='<div class="note2">'+(ev?'El partido todavía no ha empezado. El marcador aparecerá aquí en cuanto ruede el balón.':'El marcador en directo no está disponible para esta liga.')+'</div>';
  }
  if(o.tend)html+='<div class="tend2">'+esc(o.tend)+'</div>';
  html+='</div>';
  s.innerHTML=html;
  document.getElementById('sheetX').onclick=close;
}
function close(){OPEN=null;var s=document.getElementById('sheet');if(s)s.remove()}
document.addEventListener('click',function(e){
  var row=e.target.closest&&e.target.closest('.mrow');if(!row)return;
  e.preventDefault();
  var t=row.querySelector('.teams');var p=t.firstChild.textContent.split(' – ');
  var lgEl=row.previousElementSibling;while(lgEl&&!lgEl.classList.contains('league'))lgEl=lgEl.previousElementSibling;
  var sc=row.querySelector('.score');var tm=row.querySelector('.time');
  OPEN={h:p[0],a:p[1],lg:lgEl?lgEl.textContent:'',tend:(row.querySelector('.tend')||{}).textContent,score:sc?sc.textContent:'',time:tm&&tm.firstChild?tm.firstChild.textContent:''};
  var s=document.createElement('div');s.id='sheet';s.addEventListener('click',function(ev){if(ev.target===s)close()});document.body.appendChild(s);drawSheet();
},true);
document.addEventListener('keydown',function(e){if(e.key==='Escape')close()});
var box=document.getElementById('matches');
if(box){new MutationObserver(apply).observe(box,{childList:true})}
load();setInterval(load,60000);
})();
