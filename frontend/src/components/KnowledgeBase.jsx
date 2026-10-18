import { useState, useEffect, useCallback, useMemo } from 'react';
import { BookOpen, FileText, Plus, Search, Trash2, X, Save, Lightbulb, HelpCircle, PenLine } from 'lucide-react';
import { getArticles, getArticle, saveArticle, deleteArticle, getGaps, resolveGap } from '../api';
import { CategoryBadge, Empty } from './ui';
import { Suggestions, Gaps } from './KnowledgeLearning';
import { timeAgo, titleFromQuestion } from '../lib/format';

const CATEGORY_HELP = {
  general: 'Used for every email',
  sales: 'Plans, prices, offers',
  inquiry: 'How-to and general questions',
  billing: 'Invoices, payments, refunds',
  support: 'Fixing problems',
  bug: 'Known technical issues',
};

// Same splitting rules as backend/knowledge.py chunk_text(), so the editor's
// chunk count matches what the server will store.
function countChunks(text, size) {
  const paragraphs = text.split(/\n\s*\n/).map((p) => p.trim()).filter(Boolean);
  const pieces = [];
  for (const para of paragraphs) {
    if (para.length <= size) { pieces.push(para); continue; }
    let buf = '';
    for (let sentence of para.split(/(?<=[.!?])\s+|\n/)) {
      if (!sentence.trim()) continue;
      if (buf && buf.length + sentence.length + 1 > size) { pieces.push(buf.trim()); buf = ''; }
      while (sentence.length > size) { pieces.push(sentence.slice(0, size)); sentence = sentence.slice(size); }
      buf += sentence + '\n';
    }
    if (buf.trim()) pieces.push(buf.trim());
  }
  let count = 0;
  let merged = '';
  for (const piece of pieces) {
    if (merged && merged.length + piece.length + 2 > size) { count += 1; merged = ''; }
    merged = merged ? `${merged}\n\n${piece}` : piece;
  }
  return merged ? count + 1 : count;
}

const BLANK = { id: null, title: '', category: 'general', lang: 'en', content: '' };

/**
 * KnowledgeBase — the team edits what the AI knows. Text only.
 * Articles are grouped by category; the AI prefers articles matching the email's topic.
 */
function Articles({ onToast, prefill, onPrefillUsed, onChanged }) {
  const [articles, setArticles] = useState([]);
  const [usage, setUsage] = useState(null);
  const [filter, setFilter] = useState('all');
  const [search, setSearch] = useState('');
  const [draft, setDraft] = useState(null);      // article being edited (null = none selected)
  const [original, setOriginal] = useState(null); // last saved copy, to detect unsaved changes
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const res = await getArticles();
      setArticles(res.articles);
      setUsage(res.usage);
    } catch (err) {
      onToast(err.message, 'error');
    } finally {
      setLoading(false);
    }
  }, [onToast]);

  useEffect(() => { load(); }, [load]);

  // Opened from "Unanswered questions": start a new article pre-filled with the question
  useEffect(() => {
    if (!prefill) return;
    const a = { ...BLANK, ...prefill };
    setDraft(a);
    setOriginal({ ...a, content: '' });
    onPrefillUsed();
  }, [prefill, onPrefillUsed]);

  const dirty = draft && original && JSON.stringify(draft) !== JSON.stringify(original);

  const confirmDiscard = () => !dirty || window.confirm('You have unsaved changes. Discard them?');

  const open = async (id) => {
    if (!confirmDiscard()) return;
    try {
      const art = await getArticle(id);
      const a = { id: art.id, title: art.title, category: art.category, lang: art.lang, content: art.content };
      setDraft(a);
      setOriginal(a);
    } catch (err) {
      onToast(err.message, 'error');
    }
  };

  const startNew = () => {
    if (!confirmDiscard()) return;
    const a = { ...BLANK, category: filter !== 'all' ? filter : 'general' };
    setDraft(a);
    setOriginal(a);
  };

  const save = async () => {
    setSaving(true);
    try {
      const res = await saveArticle(draft);
      const a = res.article;
      const saved = { id: a.id, title: a.title, category: a.category, lang: a.lang, content: a.content };
      setDraft(saved);
      setOriginal(saved);
      setUsage(res.usage);
      onToast(draft.id ? 'Article updated — the AI uses it right away.' : 'Article added — the AI uses it right away.');
      if (!draft.id && draft.gapId) resolveGap(draft.gapId).catch(() => {});
      load();
      onChanged?.();
    } catch (err) {
      onToast(err.message, 'error');
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!window.confirm(`Delete "${draft.title}"? The AI will stop using it.`)) return;
    try {
      const res = await deleteArticle(draft.id);
      setUsage(res.usage);
      setDraft(null);
      setOriginal(null);
      onToast('Article deleted.');
      load();
    } catch (err) {
      onToast(err.message, 'error');
    }
  };

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    return articles.filter((a) =>
      (filter === 'all' || a.category === filter) &&
      (!q || a.title.toLowerCase().includes(q) || a.excerpt?.toLowerCase().includes(q)));
  }, [articles, filter, search]);

  const categories = usage?.categories ?? Object.keys(CATEGORY_HELP);

  return (
    <>
      {usage && (
        <div className="section-head">
          <div className="section-desc">Paste text, pick a topic, save — replies use it immediately.</div>
          <UsageMeter usage={usage} />
        </div>
      )}

      <div className="chips">
        <button className={`chip ${filter === 'all' ? 'active' : ''}`} onClick={() => setFilter('all')}>
          All<span className="chip-n">{usage?.articles ?? 0}</span>
        </button>
        {categories.map((c) => (
          <button
            key={c}
            className={`chip ${filter === c ? 'active' : ''}`}
            onClick={() => setFilter(c)}
            title={CATEGORY_HELP[c]}
          >
            {c}<span className="chip-n">{usage?.by_category?.[c] ?? 0}</span>
          </button>
        ))}
      </div>

      <div className="md-layout">
        <div className="card">
          <div className="card-head">
            <label className="input-icon" style={{ flex: 1 }}>
              <Search size={15} />
              <input className="input" placeholder="Search articles…" value={search} onChange={(e) => setSearch(e.target.value)} />
            </label>
            <button className="btn btn-primary" onClick={startNew}><Plus size={15} />New</button>
          </div>
          <div className="md-list">
            {loading ? (
              <div className="skeleton" style={{ height: 200, margin: 16 }} />
            ) : visible.length === 0 ? (
              <Empty icon={BookOpen} title="No articles here">Click “+ New” to add one.</Empty>
            ) : visible.map((a) => (
              <button
                key={a.id}
                className={`md-item ${draft?.id === a.id ? 'active' : ''}`}
                onClick={() => open(a.id)}
              >
                <span className="md-item-title">{a.title}</span>
                <span className="md-item-meta">
                  <CategoryBadge category={a.category} />
                  <span>{a.lang.toUpperCase()}</span>
                  <span>· {a.chunk_count} chunk{a.chunk_count === 1 ? '' : 's'}</span>
                  <span>· {timeAgo(a.updated_at)}</span>
                </span>
                <span className="md-item-excerpt">{a.excerpt}</span>
              </button>
            ))}
          </div>
        </div>

        <div className="card">
          {!draft ? (
            <Empty icon={FileText} title="Select an article or create a new one">
              Tip: keep one topic per article (for example “Changing DNS settings”) — the AI finds focused articles more easily.
            </Empty>
          ) : (
            <Editor
              draft={draft}
              setDraft={setDraft}
              usage={usage}
              dirty={dirty}
              saving={saving}
              onSave={save}
              onDelete={remove}
              onClose={() => { if (confirmDiscard()) { setDraft(null); setOriginal(null); } }}
            />
          )}
        </div>
      </div>
    </>
  );
}

function Editor({ draft, setDraft, usage, dirty, saving, onSave, onDelete, onClose }) {
  const set = (key) => (e) => setDraft((d) => ({ ...d, [key]: e.target.value }));
  const maxChars = usage?.max_article_chars ?? 15000;
  const chunkChars = usage?.chunk_chars ?? 900;
  const chars = draft.content.length;
  const chunks = useMemo(() => countChunks(draft.content.trim(), chunkChars), [draft.content, chunkChars]);
  const over = chars > maxChars;
  const canSave = dirty && draft.title.trim() && draft.content.trim() && !over && !saving;

  return (
    <>
      <div className="card-head">
        <span className="card-title"><PenLine size={16} />{draft.id ? 'Edit article' : 'New article'}</span>
        <div className="toolbar">
          {draft.id && <button className="btn btn-danger btn-sm" onClick={onDelete}><Trash2 size={14} />Delete</button>}
          <button className="btn btn-sm" onClick={onClose}><X size={14} />Close</button>
          <button className="btn btn-primary btn-sm" disabled={!canSave} onClick={onSave}>
            <Save size={14} />{saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
      <div className="card-body editor">
        <div className="field-row">
          <div className="field">
            <label className="field-label" htmlFor="kb-title">Title</label>
            <input
              id="kb-title"
              className="input"
              value={draft.title}
              maxLength={200}
              placeholder="e.g. Hosting plans and prices"
              onChange={set('title')}
            />
          </div>
          <div className="field">
            <label className="field-label" htmlFor="kb-cat">Topic</label>
            <select id="kb-cat" className="select" value={draft.category} onChange={set('category')}>
              {(usage?.categories ?? Object.keys(CATEGORY_HELP)).map((c) => (
                <option key={c} value={c}>{c[0].toUpperCase() + c.slice(1)}</option>
              ))}
            </select>
          </div>
          <div className="field">
            <label className="field-label" htmlFor="kb-lang">Language</label>
            <select id="kb-lang" className="select" value={draft.lang} onChange={set('lang')}>
              <option value="en">English</option>
              <option value="fi">Finnish</option>
            </select>
          </div>
        </div>
        <div className="field-hint">{CATEGORY_HELP[draft.category]}</div>
        {draft.question && (
          <div className="reason"><HelpCircle size={15} />Customers asked: “{draft.question}”</div>
        )}

        <div className="field">
          <label className="field-label" htmlFor="kb-content">Content (plain text)</label>
          <textarea
            id="kb-content"
            className="textarea"
            rows={18}
            value={draft.content}
            placeholder={'Paste or write the information here.\n\nSeparate topics with an empty line — each paragraph is kept together when the AI searches.'}
            onChange={set('content')}
          />
          <div className={`counter ${over ? 'over' : ''}`}>
            <span>{chars.toLocaleString()} / {maxChars.toLocaleString()} characters</span>
            <span>{chunks} chunk{chunks === 1 ? '' : 's'}</span>
          </div>
          {over && <div className="field-hint" style={{ color: 'var(--red)' }}>Too long — split this into two articles.</div>}
        </div>
      </div>
    </>
  );
}

function UsageMeter({ usage }) {
  const pct = Math.min(100, Math.round((usage.chunks_used / usage.max_total_chunks) * 100));
  const color = pct > 90 ? 'var(--red)' : pct > 70 ? 'var(--amber)' : 'var(--primary)';
  return (
    <div className="meter" title="Total size limit of the knowledge base, so the AI model is never overloaded">
      <div className="meter-top">
        <span>Storage used</span>
        <span><b>{usage.chunks_used}</b> / {usage.max_total_chunks} chunks</span>
      </div>
      <div className="bar-track">
        <div className="bar-fill" style={{ width: `${pct}%`, background: color }} />
      </div>
    </div>
  );
}


/**
 * KnowledgeBase — articles plus the self-learning inputs (suggestions & unanswered questions).
 */
export default function KnowledgeBase({ onToast }) {
  const [tab, setTab] = useState('articles');
  const [counts, setCounts] = useState({ suggestions: 0, gaps: 0 });
  const [prefill, setPrefill] = useState(null);

  const refreshCounts = useCallback(() => {
    getGaps().then((r) => setCounts(r.counts)).catch(() => {});
  }, []);
  useEffect(() => { refreshCounts(); }, [refreshCounts]);

  const clearPrefill = useCallback(() => setPrefill(null), []);

  const writeFromGap = (gap) => {
    setPrefill({
      title: titleFromQuestion(gap.question),
      category: gap.category,
      lang: gap.lang,
      question: gap.question,
      gapId: gap.id,
    });
    setTab('articles');
  };

  const tabs = [
    ['articles', 'Articles', BookOpen, 0],
    ['suggestions', 'Suggested', Lightbulb, counts.suggestions],
    ['gaps', 'Unanswered questions', HelpCircle, counts.gaps],
  ];

  return (
    <>
      <div className="section-head">
        <div>
          <div className="section-desc">What the AI knows — and what it is learning from your team.</div>
        </div>
      </div>
      <div className="subtabs">
        {tabs.map(([id, label, Icon, n]) => (
          <button key={id} className={`subtab ${tab === id ? 'active' : ''}`} onClick={() => setTab(id)}>
            <Icon size={15} />{label}
            {n > 0 && <span className="nav-count">{n}</span>}
          </button>
        ))}
      </div>

      {tab === 'articles' && (
        <Articles onToast={onToast} prefill={prefill} onPrefillUsed={clearPrefill} onChanged={refreshCounts} />
      )}
      {tab === 'suggestions' && <Suggestions onToast={onToast} onCounts={setCounts} />}
      {tab === 'gaps' && <Gaps onToast={onToast} onCounts={setCounts} onWrite={writeFromGap} />}
    </>
  );
}
