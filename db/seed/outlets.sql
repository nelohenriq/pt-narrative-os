-- pt-media-os V1 — Seed data: Portuguese outlets
-- 20 outlets covering mainstream, economic, sports, and agency sources
-- Last updated: 2026-04-25

-- ============================================================================
-- OWNERS (major media groups in Portugal)
-- ============================================================================

INSERT INTO owners (id, name, slug, owner_type, country, erc_reference, confidence, notes) VALUES
('a0000001-0000-0000-0000-000000000001', 'Impresa', 'impresa', 'company', 'PT', NULL, 0.9, 'Expresso, SIC, Caras'),
('a0000001-0000-0000-0000-000000000002', 'Global Media Group', 'global-media', 'company', 'PT', NULL, 0.8, 'DN, JN, SÁBADO, Sol'),
('a0000001-0000-0000-0000-000000000003', 'Cofina Media', 'cofina', 'company', 'PT', NULL, 0.9, 'CM, Record, O Jogo, A Bola, Jornal de Negócios'),
('a0000001-0000-0000-0000-000000000004', 'RTP — Rádio e Televisão de Portugal', 'rtp', 'state', 'PT', NULL, 1.0, 'Public service broadcaster'),
('a0000001-0000-0000-0000-000000000005', 'Observador — Media Livre', 'media-livre', 'company', 'PT', NULL, 0.7, 'Independent digital-native outlet'),
('a0000001-0000-0000-0000-000000000006', 'Lusa — Agência de Notícias de Portugal', 'lusa-sa', 'company', 'PT', NULL, 0.9, 'State-backed news agency'),
('a0000001-0000-0000-0000-000000000007', 'Trust in News / Renascimento Media', 'renascimento', 'company', 'PT', NULL, 0.6, 'i newspaper'),
('a0000001-0000-0000-0000-000000000008', 'SAPO', 'sapo', 'company', 'PT', NULL, 0.5, 'Altice group; portal with editorial content');

-- ============================================================================
-- OUTLETS
-- ============================================================================

INSERT INTO outlets (id, name, slug, outlet_type, website_url, feed_url, active) VALUES

-- Major national dailies
('b0000001-0000-0000-0000-000000000001', 'Público', 'publico', 'newspaper',
 'https://publico.pt', 'https://feeds.feedburner.com/PublicoRSS', TRUE),

('b0000001-0000-0000-0000-000000000002', 'Expresso', 'expresso', 'newspaper',
 'https://expresso.pt', NULL, TRUE),

('b0000001-0000-0000-0000-000000000003', 'Diário de Notícias', 'dn', 'newspaper',
 'https://www.dn.pt', NULL, TRUE),

('b0000001-0000-0000-0000-000000000004', 'Jornal de Notícias', 'jn', 'newspaper',
 'https://www.jn.pt', 'https://www.jn.pt/RSS', TRUE),

-- Digital-native / magazine
('b0000001-0000-0000-0000-000000000005', 'Observador', 'observador', 'news_site',
 'https://observador.pt', NULL, TRUE),

('b0000001-0000-0000-0000-000000000006', 'SÁBADO', 'sabado', 'magazine',
 'https://www.sabado.pt', 'https://www.sabado.pt/rss', TRUE),

('b0000001-0000-0000-0000-000000000007', 'Sol', 'sol', 'magazine',
 'https://sol.sapo.pt', NULL, TRUE),

('b0000001-0000-0000-0000-000000000008', 'i', 'i', 'newspaper',
 'https://ionline.pt', NULL, TRUE),

-- Popular / tabloid
('b0000001-0000-0000-0000-000000000009', 'Correio da Manhã', 'cm', 'newspaper',
 'https://www.cmjornal.pt', 'https://www.cmjornal.pt/rss', TRUE),

-- Sports
('b0000001-0000-0000-0000-000000000010', 'O Jogo', 'o-jogo', 'newspaper',
 'https://www.ojogo.pt', NULL, TRUE),

('b0000001-0000-0000-0000-000000000011', 'Record', 'record', 'newspaper',
 'https://www.record.pt', NULL, TRUE),

('b0000001-0000-0000-0000-000000000012', 'A Bola', 'a-bola', 'newspaper',
 'https://www.abola.pt', NULL, TRUE),

-- Business / economy
('b0000001-0000-0000-0000-000000000013', 'Económico', 'economico', 'news_site',
 'https://economico.sapo.pt', NULL, TRUE),

('b0000001-0000-0000-0000-000000000014', 'Jornal de Negócios', 'negocios', 'newspaper',
 'https://www.jornaldenegocios.pt', 'https://www.jornaldenegocios.pt/funcionalidades/Rss.aspx', TRUE),

('b0000001-0000-0000-0000-000000000015', 'Jornal Económico', 'jornal-economico', 'news_site',
 'https://jornaleconomico.sapo.pt', NULL, TRUE),

-- Broadcasters (online news sections)
('b0000001-0000-0000-0000-000000000016', 'RTP Notícias', 'rtp', 'tv_online',
 'https://www.rtp.pt/noticias', 'https://www.rtp.pt/noticias/rss', TRUE),

('b0000001-0000-0000-0000-000000000017', 'SIC Notícias', 'sic-noticias', 'tv_online',
 'https://sicnoticias.pt', 'https://sicnoticias.pt/rss', TRUE),

('b0000001-0000-0000-0000-000000000018', 'TVI', 'tvi', 'tv_online',
 'https://tvi.iol.pt', NULL, TRUE),

-- News agency
('b0000001-0000-0000-0000-000000000019', 'Lusa', 'lusa', 'agency',
 'https://www.lusa.pt', NULL, TRUE),

-- Regional
('b0000001-0000-0000-0000-000000000020', 'Diário de Coimbra', 'diario-coimbra', 'newspaper',
 'https://www.diariocoimbra.pt', NULL, TRUE);

-- ============================================================================
-- OWNERSHIP LINKS
-- ============================================================================

INSERT INTO outlet_ownership (outlet_id, owner_id, stake_pct, confidence, source) VALUES

-- Impresa
('b0000001-0000-0000-0000-000000000002', 'a0000001-0000-0000-0000-000000000001', 100.0, 0.9, 'ERC/public records'),
('b0000001-0000-0000-0000-000000000017', 'a0000001-0000-0000-0000-000000000001', 100.0, 0.9, 'ERC/public records'),

-- Global Media Group
('b0000001-0000-0000-0000-000000000003', 'a0000001-0000-0000-0000-000000000002', NULL, 0.7, 'press reports'),
('b0000001-0000-0000-0000-000000000004', 'a0000001-0000-0000-0000-000000000002', NULL, 0.7, 'press reports'),
('b0000001-0000-0000-0000-000000000006', 'a0000001-0000-0000-0000-000000000002', NULL, 0.7, 'press reports'),
('b0000001-0000-0000-0000-000000000007', 'a0000001-0000-0000-0000-000000000002', NULL, 0.6, 'press reports'),

-- Cofina
('b0000001-0000-0000-0000-000000000009', 'a0000001-0000-0000-0000-000000000003', 100.0, 0.9, 'ERC/public records'),
('b0000001-0000-0000-0000-000000000011', 'a0000001-0000-0000-0000-000000000003', 100.0, 0.9, 'ERC/public records'),
('b0000001-0000-0000-0000-000000000010', 'a0000001-0000-0000-0000-000000000003', 100.0, 0.9, 'ERC/public records'),
('b0000001-0000-0000-0000-000000000012', 'a0000001-0000-0000-0000-000000000003', 100.0, 0.9, 'ERC/public records'),
('b0000001-0000-0000-0000-000000000014', 'a0000001-0000-0000-0000-000000000003', NULL, 0.7, 'press reports'),

-- RTP (state-owned)
('b0000001-0000-0000-0000-000000000016', 'a0000001-0000-0000-0000-000000000004', 100.0, 1.0, 'public statute'),

-- Observador (independent)
('b0000001-0000-0000-0000-000000000005', 'a0000001-0000-0000-0000-000000000005', NULL, 0.6, 'self-reported'),

-- Lusa (state-backed)
('b0000001-0000-0000-0000-000000000019', 'a0000001-0000-0000-0000-000000000006', NULL, 0.9, 'public statute'),

-- i / Renascimento
('b0000001-0000-0000-0000-000000000008', 'a0000001-0000-0000-0000-000000000007', NULL, 0.5, 'press reports'),

-- Económico / SAPO (Altice)
('b0000001-0000-0000-0000-000000000013', 'a0000001-0000-0000-0000-000000000008', NULL, 0.5, 'press reports');

-- ============================================================================
-- NOTES
-- ============================================================================
--
-- Feed URLs with NULL: These outlets don't expose a public RSS/Atom feed
-- or their feed URL is behind a paywall/JS-rendered page.
-- The ingestion service should handle these via:
--   1. Sitemap.xml parsing (many sites have /sitemap.xml)
--   2. HTML scraping of article listing pages
--   3. Future: API access or partnership feeds
--
-- Feed URLs may change. Verify before first production run.
-- Some outlets (Impresa/Global Media) share content management platforms
-- so similar feed URL patterns may apply across their properties.
--
-- Ownership data is best-effort based on public records and press reports.
-- ERC (Entidade Reguladora para a Comunicação Social) publishes official
-- ownership data at https://www.erc.pt — should be cross-referenced.
--
