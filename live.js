(function(){
var STOP=/\b(fc|sc|cf|ac|cd|ca|club|de|del|la|el|the|sk|fk|afc|united|utd|city|real|atletico|sporting|deportivo|san|santa|universidad|sport|super|giant)\b/g;
function norm(s){return String(s).normalize('NFD').replace(/[̀-ͯ]/g,'').toLowerCase().replace(/[^a-z0-9 ]/g,' ').replace(STOP,' ').replace(/\s+/g,' ').trim()}
function toks(s){return norm(s).split(' ').filter(function(w){return w.length>2})}
function sim(a,b){var A=toks(a),B=toks(b);return A.some(function(x){return B.some(function(y){return x===y||(x.length>3&&y.length>3&&(x.indexOf(y)===0||y.indexOf(x)===0))})})}
var EV=[];
function today(){var d=new Date();return d.getFullYear()+String(d.getMonth()+1).padStart(2,'0')+String(d.getDate()).padStart(2,'0')}
function load(){
  fetch('https://site.api.espn.com/apis/site/v2/sports/soccer/all/scoreboard?dates='+today()).then(function(r){return r.json()}).then(function(j){
    EV=(j.events||[]).map(function(e){var c=e.competitions[0].competitors;var h=c.filter(function(x){return x.homeAway==='home'})[0]||c[0],a=c.filter(function(x){return x.homeAway==='away'})[0]||c[1];
      return {h:h.team.displayName,a:a.team.displayName,hs:h.score,as:a.score,st:e.status.type.state,det:e.status.type.shortDetail||''}});
    apply();
  }).catch(function(){});
}
function apply(){
  document.querySelectorAll('.mrow').forEach(function(row){
    var t=row.querySelector('.teams');if(!t||!t.firstChild)return;
    var p=t.firstChild.textContent.split(' – ');if(p.length<2)return;
    var ev=EV.filter(function(e){return sim(e.h,p[0])&&sim(e.a,p[1])})[0];
    if(!ev||ev.st==='pre')return;
    var side=row.querySelector('.side'),sc=side.querySelector('.score');
    if(!sc){sc=document.createElement('span');sc.className='score';side.insertBefore(sc,side.firstChild)}
    var v=ev.hs+' - '+ev.as;if(sc.textContent!==v)sc.textContent=v;
    var tm=row.querySelector('.time small');
    if(ev.st==='in'){row.classList.add('live');var lab=/HT|Half/i.test(ev.det)?'DESCANSO':ev.det;
      if(tm){tm.className='st-live';tm.innerHTML='<span class="blink"></span>'+lab.replace(/[<>&]/g,'')}}
    else if(ev.st==='post'){row.classList.remove('live');if(tm){tm.className='st-end';tm.textContent='FINAL'}}
  });
}
var box=document.getElementById('matches');
if(box){new MutationObserver(apply).observe(box,{childList:true})}
load();setInterval(load,60000);
})();
