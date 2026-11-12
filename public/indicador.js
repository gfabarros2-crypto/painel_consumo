/* Insira <empetur-consumo-indicador></empetur-consumo-indicador> na página inicial. */
(() => {
  const base = new URL('.', document.currentScript.src);
  const labels = { water: 'Água', energy: 'Energia' };
  const colors = { conscious: '#14699a', adequate: '#237748', alert: '#8d6500', abusive: '#ae3d37', pending: '#6956a1', unavailable: '#697e8e' };
  class EmpeturConsumoIndicador extends HTMLElement {
    connectedCallback() {
      const root = this.attachShadow({ mode: 'open' });
      const style = document.createElement('style');
      style.textContent = `:host{display:block;font-family:Arial,sans-serif;color:#173a54}.box{border:1px solid #d8e6ee;border-radius:14px;padding:16px;background:#fff;max-width:410px}.title{font-size:12px;letter-spacing:.08em;text-transform:uppercase;font-weight:800;margin:0 0 12px}.items{display:grid;gap:9px}.item{display:flex;justify-content:space-between;align-items:center;gap:15px;font-size:13px}.status{display:flex;align-items:center;gap:7px;font-weight:700}.dot{width:10px;height:10px;border-radius:50%;background:var(--status)}a{display:inline-block;margin-top:13px;color:#0879a9;font-size:12px;font-weight:800;text-decoration:none}a:hover{text-decoration:underline}`;
      const box = document.createElement('section');
      box.className = 'box';
      const title = document.createElement('p');
      title.className = 'title';
      title.textContent = 'Consumo de água e energia';
      const items = document.createElement('div');
      items.className = 'items';
      items.setAttribute('role', 'status');
      items.textContent = 'Carregando indicador…';
      const link = document.createElement('a');
      link.href = new URL('index.html', base).href;
      link.textContent = 'Consultar painel completo ↗';
      box.append(title, items, link);
      root.append(style, box);
      fetch(new URL('api/overview', base), { cache: 'no-store' })
        .then((response) => { if (!response.ok) throw new Error(); return response.json(); })
        .then((data) => {
          items.replaceChildren();
          ['water', 'energy'].forEach((resource) => {
            const item = document.createElement('div');
            item.className = 'item';
            const name = document.createElement('span');
            name.textContent = labels[resource];
            const status = document.createElement('span');
            status.className = 'status';
            const dot = document.createElement('span');
            const code = data[resource]?.status?.code || 'unavailable';
            dot.className = 'dot';
            dot.style.setProperty('--status', colors[code] || colors.unavailable);
            dot.setAttribute('aria-hidden', 'true');
            const text = document.createElement('span');
            text.textContent = data[resource]?.status?.label || 'Sem dados';
            status.append(dot, text);
            item.append(name, status);
            items.append(item);
          });
        })
        .catch(() => { items.textContent = 'Indicador temporariamente indisponível.'; });
    }
  }
  customElements.define('empetur-consumo-indicador', EmpeturConsumoIndicador);
})();
