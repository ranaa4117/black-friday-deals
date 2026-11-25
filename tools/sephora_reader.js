/* Sephora USA reader — runs inside a normal browser tab that is already showing a sephora.com page.
   It only reads what the page itself shows (its own page data and the product tiles on screen).
   Usage from the scheduled task:
     1) open a Sephora page, 2) paste this file, 3) call  await SR.content()  or  await SR.sale(label),
     4) read window.__srOut in parts:  window.__srOut.slice(a, b)
   Output is JSON text; nothing is sent anywhere. */
(() => {
  const ORIGIN = "https://www.sephora.com";
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const abs = u => !u ? "" : u.startsWith("http") ? u : ORIGIN + (u.startsWith("/") ? "" : "/") + u;
  function rich(n){   // Contentful rich text → plain text with line breaks
    if (!n) return "";
    if (typeof n === "string") return n;
    if (n.json) return rich(n.json);
    if (n.nodeType === "text") return n.value || "";
    const inner = (n.content || []).map(rich).join("");
    return /paragraph|heading|list-item/.test(n.nodeType || "") ? inner.trim() + "\n" : inner;
  }
  function link(a){
    if (!a) return "";
    if (a.type === "ActionLinkExternal" || (a.targetUrl && !a.page)) return abs(a.targetUrl || "");
    const p = a.page || {}, q = a.urlParameters ? "?" + String(a.urlParameters).replace(/^\?/, "") : "";
    const path = p.type === "PageContent" ? "/beauty/" + p.slug : p.type === "PageBrand" ? "/brand/" + p.slug : p.type === "PageCategory" ? "/shop/" + p.slug
      : p.type === "PageSearch" ? "/search?keyword=" + encodeURIComponent(p.keyword || "") : p.type === "PageHappening" ? "/happening/" + (p.slug || "") : p.type === "PageProduct" ? "/product/" + (p.slug || "") : "";
    return path ? abs(path) + (path.includes("?") ? q.replace("?", "&") : q) : "";
  }
  const media = m => m && m.src ? { src: abs(m.src), alt: m.altText || "", w: m.width, h: m.height } : null;
  function sku(s){
    return { sku: s.skuId, pid: s.productId, brand: s.brandName, name: s.productName, list: s.listPrice, sale: s.salePrice || null, value: s.valuePrice || null,
      variation: s.variationValue || "", url: abs(s.targetUrl), img: (s.skuImages && s.skuImages.imageUrl) || "", bi: s.biExclusiveLevel || "none",
      rating: s.starRatings || null, reviews: s.reviewsCount || null, oos: !!(s.actionFlags && /notify|outOfStock/i.test(JSON.stringify(s.actionFlags))) };
  }
  function offer(i){
    return { id: i.promoId || i.sid, title: i.title || "", desc: i.description || "", code: i.promoCode || "", threshold: i.threshold || "",
      eligibility: i.eligibility || [], legal: i.legalCopy || "", media: media(i.media), details: link(i.detailsAction), detailsLabel: i.detailsActionLabel || "",
      action: link(i.action), skus: (i.skuList || []).map(sku), placement: ((i.featuresDataCollection || {}).items || []).map(x => x.key + "=" + x.value) };
  }
  function banner(b){ return { text: rich(b.text).trim(), media: media(b.media) || media(b.largeMedia), url: link(b.action), bg: b.backgroundColor || "", color: b.color || "" }; }
  function comp(x){
    const base = { type: x.type, sid: x.sid || "", title: x.title || "" };
    if (x.type === "ProductList") return Object.assign(base, { variant: x.variant || "", more: link(x.action), moreLabel: x.actionLabel || "", products: (x.skuList || []).map(sku) });
    if (x.type === "PromotionList") return Object.assign(base, { personalized: !x.items || !!x.personalization, offers: (x.items || []).map(offer) });
    if (x.type === "BannerList") return Object.assign(base, { banners: (x.items || []).map(banner) });
    if (x.type === "Banner") return Object.assign(base, { banners: [banner(x)] });
    if (x.type === "SoftLinks") return Object.assign(base, { links: (x.items || []).map(l => ({ label: l.label || rich(l.text).trim(), url: link(l.action) })) });
    if (x.type === "Copy") return Object.assign(base, { text: rich(x.content).trim().slice(0, 4000) });
    return base;
  }
  function nav(n){
    if (!n) return null;
    return { label: n.label || "", desc: n.description || "", url: link(n.action), current: !!(n.action && n.action.isCurrent), media: media(n.media), items: (n.items || []).map(nav) };
  }
  async function content(){
    const ls = document.getElementById("linkStore");
    if (!ls) throw new Error("no page data on this page");
    const page = JSON.parse(ls.textContent).page || {};
    const c = page.content || {}, L = c.layout || {};
    const out = { kind: "content", url: location.href.split("?")[0], title: document.title, readAt: new Date().toISOString(), slug: c.slug || "",
      hero: L.heroBanner ? banner(L.heroBanner) : null, navigation: nav(c.navigation), sections: (L.content || []).map(comp).filter(s => s.type !== "Anchor") };
    window.__srOut = JSON.stringify(out); return { bytes: window.__srOut.length, sections: out.sections.length };
  }
  /* sale listing: scroll so every tile renders, press "Show More Products" until the list is complete */
  async function sale(label, maxMs = 240000){
    const M = new Map(), t0 = Date.now();
    const total = () => { const m = (document.querySelector("main") || document.body).innerText.match(/of ([\d,]+) Results/); return m ? Number(m[1].replace(/,/g, "")) : null; };
    const grab = () => { for (const a of document.querySelectorAll('main a[href*="/product/"]')){
      const h = a.getAttribute("href").split("&icid2")[0], id = (h.match(/-(P\d+)/) || [])[1]; if (!id) continue;
      const im = a.querySelector("img"), t = a.innerText.split("\n").map(s => s.trim()).filter(Boolean);
      if (t.length < 2) continue;
      M.set(id, { pid: id, url: abs(h), t, img: im ? (im.currentSrc || im.src || "") : "" }); } };
    let stall = 0, last = -1;
    while (Date.now() - t0 < maxMs){
      grab(); scrollBy(0, innerHeight * 0.9); await sleep(350);
      if (M.size === last) stall++; else { stall = 0; last = M.size; }
      if (stall > 4){
        const btn = [...document.querySelectorAll("button")].find(b => /Show More Products/i.test(b.textContent));
        if (!btn) break;
        btn.click(); await sleep(2500); stall = 0;
      }
    }
    grab();
    const out = { kind: "sale", label, url: location.href, readAt: new Date().toISOString(), total: total(), complete: total() == null || M.size >= total(), items: [...M.values()] };
    window.__srOut = JSON.stringify(out); return { bytes: window.__srOut.length, items: M.size, total: out.total, complete: out.complete, ms: Date.now() - t0 };
  }
  /* product page (for gift-set contents): the page's own product data */
  async function product(){
    const ls = document.getElementById("linkStore"); const page = ls ? JSON.parse(ls.textContent).page || {} : {};
    const p = page.product || {}, cs = p.currentSku || {}, info = p.productDetails || {};
    const out = { kind: "product", url: location.href, pid: info.productId || p.productId, brand: (info.brand || {}).displayName, name: info.displayName,
      list: cs.listPrice, sale: cs.salePrice || null, value: cs.valuePrice || null, size: cs.size || cs.variationValue || "", skuType: cs.skuType || "",
      desc: (info.longDescription || "").slice(0, 6000), sets: cs.setIncludes || null, img: (cs.skuImages || {}).imageUrl || "",
      variants: (p.regularChildSkus || []).map(s => ({ sku: s.skuId, name: s.variationValue || s.variationDesc || "", list: s.listPrice, sale: s.salePrice || null, oos: !!s.isOutOfStock, img: (s.skuImages || {}).imageUrl || "" })),
      bc: (page.breadcrumbs || p.parentCategory ? JSON.stringify(p.parentCategory || "").slice(0, 400) : "") };
    window.__srOut = JSON.stringify(out); return { bytes: window.__srOut.length };
  }
  /* the site's "Offers" menu (from the page's own header data): where Sephora lists its current campaigns */
  function offersMenu(){
    const ls = document.getElementById("linkStore"); if (!ls) return [];
    const h = (JSON.parse(ls.textContent).page || {}).headerFooterTemplate; const out = [];
    (function walk(o, inOffers, d){ if (!o || typeof o !== "object" || d > 12) return;
      const lab = o.label || o.title || o.name || "";
      const here = inOffers || /^offers$/i.test(String(lab).trim());
      if (here && (o.action || o.targetUrl)){ const u = link(o.action || o); if (u && /sephora\.com\/(beauty|sale|shop|brand)/.test(u)) out.push({ label: String(lab).trim(), url: u.split("?")[0] }); }
      for (const k of Object.keys(o)) walk(o[k], here, d + 1); })(h, false, 0);
    return [...new Map(out.map(x => [x.url, x])).values()].slice(0, 40);
  }
  const UPLOAD = "https://qhuerltbkvihmqzsphpv.supabase.co/rest/v1/rpc/sephora_put", PUB = "sb_publishable_K35x9gcJMqTGCuj2MFj_7w_PsQSF8mU";
  async function put(key, kind, label, data){
    const r = await fetch(UPLOAD, { method: "POST", headers: { apikey: PUB, "Content-Type": "application/json" },
      body: JSON.stringify({ p_key: key, p_kind: kind, p_label: label, p_url: location.href.split("#")[0], p_data: data }) });
    if (!r.ok) throw new Error("upload " + r.status + " " + (await r.text()).slice(0, 200));
  }
  /* one job on the current page, in the background; the task checks window.__sr until done */
  function run(job, label, key){
    window.__sr = { job, label, state: "running", startedAt: new Date().toISOString() };
    (async () => {
      try {
        let res;
        if (job === "content"){ res = await content(); const o = JSON.parse(window.__srOut); o.offersMenu = offersMenu(); await put(key, "content", label, o); res.links = (o.navigation ? [o.navigation, ...(o.navigation.items || [])] : []).map(n => n.url).filter(Boolean); res.offersMenu = o.offersMenu.map(x => x.url); }
        else if (job === "list"){ res = await sale(label); const o = JSON.parse(window.__srOut); o.items = o.items.map(it => ({ pid: it.pid, url: it.url, t: it.t.slice(0, 9), img: it.img })); await put(key, "list", label, o); }
        else if (job === "product"){ res = await product(); await put(key, "product", label, JSON.parse(window.__srOut)); }
        Object.assign(window.__sr, { state: "done", result: res, endedAt: new Date().toISOString() });
      } catch (e){ Object.assign(window.__sr, { state: "error", error: String(e && e.message || e) }); }
    })();
    return "started " + job + " " + label;
  }
  window.SR = { content, sale, product, offersMenu, run };
  return "SR ready";
})();
