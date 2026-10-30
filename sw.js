const C='aa-v5';
const CORE=['./','index.html','live.js','data.json','manifest.json','icon-192.png','icon-512.png'];
self.addEventListener('install',e=>{e.waitUntil(caches.open(C).then(c=>c.addAll(CORE)).catch(()=>{}));self.skipWaiting()});
self.addEventListener('activate',e=>{e.waitUntil(caches.keys().then(k=>Promise.all(k.filter(x=>x!==C).map(x=>caches.delete(x)))));self.clients.claim()});
// Solo archivos propios: red primero, pero si tarda más de 4 s se usa la copia guardada.
self.addEventListener('fetch',e=>{
  const req=e.request;
  if(req.method!=='GET'||new URL(req.url).origin!==self.location.origin)return;
  e.respondWith((async()=>{
    const cache=await caches.open(C);
    const net=fetch(req).then(r=>{if(r&&r.ok)cache.put(req,r.clone());return r});
    const cached=await cache.match(req,{ignoreSearch:true});
    if(!cached)return net.catch(()=>new Response('Sin conexión',{status:503}));
    const timeout=new Promise(res=>setTimeout(()=>res(cached),4000));
    return Promise.race([net.catch(()=>cached),timeout]);
  })());
});
