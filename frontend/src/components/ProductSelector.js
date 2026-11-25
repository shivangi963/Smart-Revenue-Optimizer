import React from 'react';
import { categoryIcon, categoryLabel, money, num } from '../utils/format';

export default function ProductSelector({ products, selectedId, onSelect }) {
  return (
    <section className="section products-section">
      <h2 className="section-title">🛍️ Select a Product</h2>
      <div className="products-grid">
        {products.map((p) => {
          const ratio = p.max_stock ? Math.min(p.current_stock / p.max_stock, 1) : 0;
          const level = ratio < 0.15 ? 'low' : ratio < 0.4 ? 'mid' : '';
          const change = p.current_price ? (p.current_price / p.base_price - 1) * 100 : null;
          return (
            <div key={p.id} className={`product-card ${selectedId === p.id ? 'selected' : ''}`}
                 onClick={() => onSelect(p.id)} role="button" tabIndex={0}
                 onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && onSelect(p.id)}>
              <div className="product-icon">{categoryIcon(p.category)}</div>
              <h3 className="product-name">{p.name}</h3>
              <p className="product-category">{categoryLabel(p.category)}</p>
              <div className="product-details">
                <div className="detail"><span className="label">Base price:</span><span className="value">{money(p.base_price)}</span></div>
                <div className="detail">
                  <span className="label">Price now:</span>
                  <span className="value now-price">
                    {money(p.current_price)}{change !== null && <small className="muted"> ({change > 0 ? '+' : ''}{change.toFixed(1)}%)</small>}
                  </span>
                </div>
                <div className="detail"><span className="label">Stock:</span><span className="value">{num(p.current_stock)} / {num(p.max_stock)} units</span></div>
                <div className="stock-bar"><div className={`stock-fill ${level}`} style={{ width: `${ratio * 100}%` }} /></div>
              </div>
              <button className="select-btn" type="button">{selectedId === p.id ? 'Selected' : 'Select'}</button>
            </div>
          );
        })}
        {products.length === 0 && <p className="muted">No products yet - add one in the Admin tab.</p>}
      </div>
    </section>
  );
}
