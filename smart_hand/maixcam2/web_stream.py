"""Optional latest-frame-only HTTP/MJPEG preview server.

This is a dormant, data-only sidecar: importing it opens no socket and never
imports Maix.  An integration must call ``start()`` explicitly and publish
already encoded JPEG data after the existing overlay is drawn.  Each client
has at most one in-flight JPEG; the generic socket fallback discards a client
after a bounded number of no-progress writes rather than delaying camera,
inference, or UART work.
"""

try:
    import socket as _system_socket
except ImportError:  # pragma: no cover - constrained device fallback
    _system_socket = None

try:
    import json as _json
except ImportError:  # pragma: no cover - constrained device fallback
    try:
        import ujson as _json
    except ImportError:
        _json = None


BOUNDARY = "amazinghand-frame"
MAX_REQUEST_BYTES = 1024

_CONTROL_PAGE = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>OpenSignHand 电脑网页训练主界面</title>
<style>
:root{--bg:#f3f5f2;--surface:#fff;--ink:#18332e;--muted:#75827d;--line:#e3e9e4;--accent:#247362;--accent-soft:#edf5ef;--amber:#98621a;--radius:18px}
*{box-sizing:border-box}
html{scroll-behavior:smooth;scroll-padding-top:24px}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
button,a{-webkit-tap-highlight-color:transparent}
button{font:inherit}button:focus-visible,a:focus-visible,summary:focus-visible{outline:3px solid #68aa97;outline-offset:4px}
a{color:inherit;text-decoration:none}
.app-shell{max-width:1460px;margin:0 auto;padding:0 36px 28px}
.header{display:flex;align-items:center;justify-content:space-between;gap:24px;padding:18px 0;border-bottom:1px solid var(--line)}
.brand{display:flex;align-items:center;gap:12px}
.brand-mark{display:grid;place-items:center;width:44px;height:44px;border-radius:14px;background:var(--ink);color:#d8f0e3;flex-shrink:0}
.brand-name{font-size:20px;font-weight:750;letter-spacing:-.5px;line-height:1.2}
.brand-caption,.eyebrow{font-size:10px;font-weight:650;letter-spacing:1.7px;color:var(--muted)}
.header-nav{display:flex;gap:26px;align-items:center;font-size:13px;color:var(--muted)}
.header-nav a.active{color:var(--accent);font-weight:650}
.header-nav a:hover{color:var(--accent)}
.nav-label{border:1px solid var(--line);padding:5px 10px;border-radius:20px;font-size:11px}
.intro{display:flex;justify-content:space-between;align-items:center;gap:22px;padding:20px 0 8px}
h1,h2,h3,p{margin:0}
h1{font-size:30px;font-weight:700;letter-spacing:-1px;line-height:1.35}
.intro p{margin-top:6px;color:var(--muted);font-size:13px}
.intro-note{font-size:12px;color:var(--muted);display:flex;gap:8px;align-items:center;white-space:nowrap}
.intro-note:before{content:"";height:7px;width:7px;border-radius:50%;background:var(--accent)}
.health-bar{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));border:1px solid var(--line);background:#fafcf9;border-radius:13px;margin-bottom:22px;overflow:hidden}
.health-item{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:11px 16px;border-right:1px solid var(--line)}
.health-item:last-child{border-right:0}.health-label{color:#6e7c75;font-size:12px}
.health-val{padding:3px 9px;border-radius:6px;background:#eaf0eb;color:#728078;font-size:11px;font-weight:650;white-space:nowrap}
.health-val.ok{background:#e2f1e7;color:#247352}.health-val.warn{background:#fbefd8;color:#916018}.health-val.err{background:#fbe8e5;color:#b34a3d}.health-val.unknown{background:#eaf0eb;color:#728078}
.panel{min-width:0}
.workspace-heading,.section-heading{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}
.workspace-heading h2{font-size:15px;font-weight:650}.section-heading h2{font-size:22px;letter-spacing:-.6px}
.workspace-heading .muted{font-size:11px}
.muted{font-size:11px;line-height:1.7;color:var(--muted)}
.process-wrap{margin-bottom:18px}.process-title{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0)}
.process-bar{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:8px}
.p-step{position:relative;display:flex;flex-direction:column;gap:3px;padding:10px 13px;border:1px solid transparent;border-radius:10px;background:#eaf0e9;color:#77857c}
.p-step-name{font-size:12px;font-weight:600}.p-step-tag{font-size:10px;opacity:.85}
.p-step.active{background:#fff;border-color:#6ea18b;color:var(--accent);box-shadow:0 2px 8px #18332e06}
.p-step.done{color:#3d7d60;background:#e5f0e7}.p-step.terminal-timeout{background:#fbefd8;color:#916018}.p-step.terminal-fault{background:#fbe8e5;color:#b34a3d}.p-step.terminal-cancel{background:#eaf0eb;color:#728078}
.main-grid{display:grid;grid-template-columns:318px minmax(0,1fr);gap:20px;align-items:start}
.col-left,.col-right{min-width:0}
.surface,.ai-analysis,.history-panel{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);padding:22px;box-shadow:0 4px 16px #18332e03}
.card-heading{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:18px}
.card-heading h3{font-size:15px;font-weight:650}.section-index{font-size:11px;font-weight:600;color:#90a094;letter-spacing:1px}
.badge{padding:3px 8px;background:var(--accent-soft);color:var(--accent);border-radius:6px;white-space:nowrap;font-size:10px}
.lesson-detail{margin-bottom:16px;padding:16px;background:#f1f6f0;border-radius:13px}
.detail-head{display:flex;flex-direction:column;gap:6px;align-items:flex-start;margin-bottom:10px}
.detail-head>span:first-child{display:flex;align-items:center;gap:9px}
.detail-head .emoji{font-size:27px;line-height:1.3}
.detail-head b{font-size:15px;font-weight:650}
.detail-desc{font-size:12px;line-height:1.8;color:#577263}.detail-note{margin-top:7px;font-size:10px}
.level-box{margin-bottom:14px}.level-label{font-size:11px;color:var(--muted)}
.level-buttons{display:flex;flex-wrap:wrap;gap:7px;margin:10px 0}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;min-height:40px;padding:9px 14px;border:1px solid var(--line);border-radius:9px;background:#fff;color:#425c51;font-size:12px;font-weight:600;cursor:pointer;transition:background .15s,border-color .15s,transform .15s}
.btn:hover:not(:disabled){background:#f0f6f0;border-color:#a9c7b4}.btn:active:not(:disabled){transform:translateY(1px)}
.btn:disabled,.course-btn:disabled{opacity:.38;cursor:not-allowed}
.level-buttons [data-level]{flex:1;padding:8px 4px;min-height:37px;font-size:11px}
.actions{display:grid;grid-template-columns:1fr auto;gap:8px;margin:14px 0 7px}
#signStart[hidden]{display:none}
.actions[hidden]{display:none}
.primary{background:var(--accent);border-color:var(--accent);color:#fff}.primary:hover:not(:disabled){background:#195f50;border-color:#195f50}
.danger{background:#fff;color:#a85d51;border-color:#eadbd7}.danger:hover:not(:disabled){background:#fff2ee;border-color:#e0b7ae}
.request-hint{min-height:18px;font-size:10px;color:var(--muted);margin-bottom:16px}
.course-library{border-top:1px solid var(--line);padding-top:13px}
summary{cursor:pointer;list-style:none;display:flex;align-items:center;justify-content:space-between;font-size:12px;font-weight:600}
summary::-webkit-details-marker{display:none}summary:after{content:"＋";color:#90a094;font-size:16px;font-weight:400}details[open]>summary:after{content:"−"}
.cat-tabs{display:flex;flex-wrap:wrap;gap:4px;margin:13px 0 10px}
.tab-btn{border:0;background:transparent;color:var(--muted);padding:5px 7px;font-size:10px;border-radius:5px;cursor:pointer}
.tab-btn.active{background:var(--accent-soft);color:var(--accent);font-weight:650}
.course-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px;max-height:284px;overflow-y:auto;padding:1px 3px 4px 1px;scrollbar-width:thin;scrollbar-color:#c3d3c7 transparent}
.ref-card{border:1px solid var(--line);border-radius:9px;padding:9px;display:flex;flex-direction:column;gap:7px;background:#fff;min-width:0}
.ref-card.active{border-color:#4e9b80;background:#f0f7f1}
.card-head{display:flex;align-items:center;gap:4px;font-size:11px;line-height:1.4}
.card-head b{font-weight:550}.emoji{font-size:16px}
.card-desc{display:none}
.course-btn{width:100%;min-height:28px;border:0;border-radius:5px;background:#f3f6f2;color:#708074;font-size:10px;cursor:pointer}
.course-btn:hover:not(:disabled){background:#e4efe6;color:var(--accent)}
.ref-card.active .course-btn{background:#dcece1;color:#317154}
.next-action{width:100%;margin-top:12px}
.course-guide{margin:12px 0;padding:13px;border:1px solid #c8ddd1;border-radius:10px;background:#eff7f2}
.course-guide[hidden],.course-guide button[hidden]{display:none}
.course-guide-title{font-size:14px;font-weight:650;color:var(--accent)}
.course-guide-hint{margin-top:7px;font-size:12px;line-height:1.8;color:#526b5e}
.course-steps{list-style:none;padding:0;margin:10px 0 0;display:flex;flex-wrap:wrap;gap:6px}
.course-steps li{padding:5px 7px;border-radius:6px;font-size:10px;background:#fff;color:#7a887f;border:1px solid var(--line)}
.course-steps .current{border-color:var(--accent);color:var(--accent);font-weight:650}
.course-steps .passed{background:#dcefe2;color:#317154}.course-steps .recorded{background:#fbefd8;color:#916018}
.course-guide .next-action{margin-top:10px;min-height:42px;font-size:13px}
.camera-surface{padding:20px}
.camera-label{display:flex;gap:7px;align-items:center;color:#83958a;font-size:10px;letter-spacing:.9px}
.camera-dot{width:6px;height:6px;border:1px solid #83958a;border-radius:50%}
.next-cue{padding:14px 16px;border:1px solid #c6ddd1;border-left:4px solid var(--accent);border-radius:10px;background:var(--accent-soft);margin-bottom:14px}
.cue-meta{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;color:#516c60;font-size:12px;margin-bottom:7px}
.cue-label{font-size:11px;color:var(--accent);letter-spacing:.6px}
.step-alert{color:var(--ink);font-size:16px;font-weight:650;line-height:1.65;overflow-wrap:anywhere}
.stream-box{background:#112820;border-radius:13px;overflow:hidden;position:relative;text-align:center;min-height:280px;display:grid;place-items:center}
.stream-box img{width:100%;height:auto;max-height:410px;object-fit:contain;display:block}
.video-hud{padding:9px 12px;border:1px solid #dbe7df;border-radius:8px;background:#eef5f0;color:var(--ink);text-align:left;font-size:11px;display:flex;flex-wrap:wrap;gap:5px 18px;margin-top:10px;overflow-wrap:anywhere}
.video-hud>div{min-width:0}.video-hud>div:nth-child(2){display:none}
.video-hud b{color:#a6cdb7;font-weight:500}
.stream-fallback{color:#98b5a4;padding:46px 20px;width:100%;font-size:12px;min-height:280px}
.empty-camera{width:56px;height:56px;margin:0 auto 18px;color:#708e7c}.fallback-title{font-size:16px;color:#b7cebd;margin-bottom:6px}
.stream-footnote{display:flex;justify-content:space-between;gap:8px;padding-top:10px;font-size:10px;color:var(--muted)}
.live-metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin-top:16px}
.live-metric{padding:11px 12px;background:#f5f7f3;border-radius:9px;min-width:0}
.live-metric small{display:block;font-size:10px;color:var(--muted);margin-bottom:5px}
.live-metric strong{display:block;font-size:16px;font-weight:600;overflow-wrap:anywhere;line-height:1.5}
.result-separation{margin-top:15px;padding:12px 14px;border:1px solid var(--line);border-radius:10px;background:#fafcf9}
.result-separation small{display:block;color:var(--muted);font-size:11px}
.result-separation strong{display:block;margin:3px 0;font-size:15px;color:var(--ink)}
.result-separation strong.passed{color:var(--accent)}.result-separation strong.incomplete{color:var(--amber)}
.live-caption{margin-top:15px;font-size:12px;font-weight:650}.live-caption span{font-size:10px;color:var(--muted);font-weight:400}
.coach-panel{margin-top:16px;padding:17px 19px;border-radius:13px;background:#f3f7f0;border:1px solid #e3ecdd}
.coach-head{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:5px}
.coach-head strong{font-size:13px;font-weight:650}.coach-head .badge{background:#e0ebd7;color:#66804a}
.finger-chips{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0}
.finger-chip{padding:5px 9px;background:#e7eee0;color:#607452;font-size:10px;border-radius:6px}
.finger-chip.adjust{background:#f6e9cc;color:#94631d}
#coachAdvice{font-size:12px;line-height:1.9;color:#526845}
.coach-panel .muted{font-size:10px;margin-top:7px}
.sequence-guide{margin-top:16px;padding:18px;border:1px solid #cddfd7;border-radius:13px;background:#f7faf8}
.sequence-guide h4{margin:0 0 10px;font-size:17px}.sequence-guide p{margin:9px 0;line-height:1.6}
.sequence-guide ol{margin:12px 0;padding-left:26px}.sequence-guide li{padding:5px 0;line-height:1.5}
.sequence-guide .active-step{font-weight:700;color:#176756}.sequence-guide .step-done{color:#547067}
.sequence-guide progress{width:100%;height:16px;accent-color:#237565}
.sequence-guide #sequenceChecks{white-space:pre-line;line-height:1.8}
.sequence-controls{display:flex;gap:8px;flex-wrap:wrap}.sequence-guide [hidden]{display:none!important}
.note-box{margin-top:13px;padding:12px 2px;border-top:1px solid var(--line);font-size:11px}
.note-box summary{color:#7c887f;font-size:11px}
.kv{display:grid;grid-template-columns:7em minmax(0,1fr);gap:5px 8px;font-size:11px;line-height:1.8;overflow-wrap:anywhere}
.kv span:nth-child(odd){color:var(--muted)}.kv b{font-weight:550}
.status{padding:12px;background:#f5f7f3;border-radius:8px}
.diagnostic-grid{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-top:13px}
.safety-note{line-height:1.9;font-size:10px;color:var(--muted);padding-top:10px}
.analysis-section{margin-top:32px;scroll-margin-top:24px}
.analysis-grid{display:grid;grid-template-columns:1.3fr 1fr;gap:20px;align-items:start}
.ai-analysis-head{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:8px;font-size:15px}
.ai-badge{font-size:10px;font-weight:600;padding:4px 9px;border-radius:6px;background:#edf1eb;color:#7d8b80;white-space:nowrap}
.ai-badge.loading{background:#e4f0eb;color:#31745f}.ai-badge.ready{background:#e4f0eb;color:#31745f}.ai-badge.local{background:#edf1eb;color:#24362e;border:1px dashed #5f7368}.ai-badge.error{background:#fbefd8;color:#916018}
.ai-metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin:15px 0}
.ai-metric{padding:12px;background:#f5f7f3;border-radius:9px;min-width:0}
.ai-metric small{display:block;color:var(--muted);font-size:10px;margin-bottom:4px}.ai-metric strong{display:block;overflow-wrap:anywhere;font-size:14px;font-weight:600}
.ai-result{background:#f7f9f5;border-radius:9px;padding:15px;font-size:12px;line-height:1.9;white-space:pre-wrap;overflow-wrap:anywhere;color:#647b6c;min-height:84px}
.report-brief{padding:14px 16px;border:1px solid var(--line);background:#f8faf7;border-radius:10px;margin:12px 0}
.report-brief h3{font-size:14px;margin-bottom:8px}.report-brief p{white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px;line-height:1.9}
.report-brief .muted{font-size:11px;margin-top:6px}.report-evidence{border-top:1px solid var(--line);padding-top:12px;margin-top:14px}
.report-evidence summary{min-height:44px;font-size:13px}
.report-actions{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0 8px}
.level-report{white-space:pre-wrap;overflow-wrap:anywhere;border-top:1px solid var(--line);padding-top:15px;margin:15px 0 0;font:12px/1.9 -apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif}
.history-summary{white-space:pre-wrap;font-size:12px;line-height:1.9;color:#5f7668;padding:13px 0;border-top:1px solid var(--line);margin-top:14px}
.history-actions{display:flex;gap:7px;margin:13px 0}.history-actions .btn{font-size:11px;min-height:34px;padding:6px 12px}
.remedial-btn{width:100%;background:#edf5ef;color:var(--accent);border-color:#d9e8dc;margin-top:12px}
.compat{margin-top:24px;padding:16px 20px;border:1px solid var(--line);border-radius:12px;background:#edf1ea}.compat p{font-size:12px;color:var(--muted);margin:12px 0}
.footer{display:flex;justify-content:space-between;gap:16px;margin-top:25px;border-top:1px solid var(--line);padding-top:16px;color:#8b978d;font-size:10px}
@media(min-width:1080px){.col-left{position:sticky;top:18px}}
@media(max-width:1000px){.app-shell{padding:0 22px 24px}.main-grid{grid-template-columns:280px minmax(0,1fr)}.surface,.ai-analysis,.history-panel{padding:17px}.health-item{padding:10px}.health-label{font-size:10px}.live-metric strong{font-size:13px}}
@media(max-width:760px){.app-shell{padding:0 14px 20px}.header{padding:18px 0}.header-nav{gap:15px}.nav-label{display:none}.intro{padding:21px 0 16px}.intro-note{display:none}h1{font-size:24px}.main-grid,.analysis-grid{grid-template-columns:1fr}.col-right{grid-row:1}.col-left{grid-row:2}.process-bar{gap:5px}.p-step{padding:8px 5px;text-align:center}.p-step-name{font-size:10px}.p-step-tag{font-size:9px}.health-bar{grid-template-columns:repeat(2,minmax(0,1fr));margin-bottom:17px}.health-item:nth-child(2){border-right:0}.health-item:nth-child(-n+2){border-bottom:1px solid var(--line)}.course-grid{grid-template-columns:repeat(3,minmax(0,1fr));max-height:235px}.stream-box,.stream-fallback{min-height:220px}.stream-fallback{padding:35px 15px}.live-metrics{gap:5px}.live-metric{padding:9px 8px}.live-metric strong{font-size:12px}.diagnostic-grid{grid-template-columns:1fr}.analysis-section{margin-top:24px}.footer{flex-direction:column;gap:4px}.brand-name{font-size:18px}.brand-caption{font-size:8px}.brand-mark{width:38px;height:38px}.header-nav{font-size:11px}.workspace-heading .muted{display:none}}
@media(max-width:400px){.course-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.p-step-tag{display:none}.coach-head{align-items:flex-start}.coach-head .badge{font-size:9px}.health-item{gap:5px;padding:9px 8px}}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}*,*:before,*:after{transition:none!important}}
.context-grid{display:grid;grid-template-columns:1.15fr 1fr;gap:20px;margin:24px 0;scroll-margin-top:20px}
.context-card{border:1px solid var(--line);border-radius:16px;padding:20px;background:#fff;min-width:0}
.context-card h2{font-size:18px;margin:4px 0 10px}.context-kicker{font-size:11px;letter-spacing:1px;color:var(--accent)}
.context-card p{font-size:13px;line-height:1.8;margin:8px 0;overflow-wrap:anywhere}
.context-tags,.communication-actions,.readability-tools{display:flex;gap:8px;flex-wrap:wrap}
.context-tags span{font-size:11px;background:#eef5ef;padding:4px 8px;border-radius:6px}
.context-card .boundary{border-left:3px solid #c79843;padding-left:10px;color:#785d24}
.context-card summary{cursor:pointer;font-size:12px;min-height:32px;padding-top:6px}
.context-card details p{font-size:12px;color:var(--muted)}
.context-card a{color:var(--accent);text-decoration:underline;text-underline-offset:3px}
.communication-actions .btn,.readability-tools .btn{min-height:44px;font-size:13px}
.communication-input{width:100%;box-sizing:border-box;border:1px solid #96b5a5;border-radius:8px;min-height:60px;padding:10px;font:inherit;resize:vertical}
.communication-display{margin:12px 0;padding:18px;border:2px solid var(--accent);background:#f0f7f2;border-radius:12px}
.communication-display[hidden]{display:none}.communication-display strong{font-size:clamp(28px,4vw,48px);line-height:1.5;display:block;overflow-wrap:anywhere;white-space:pre-wrap;margin-bottom:12px}
.readability-tools{margin:12px 0 16px;align-items:center}.readability-tools span{font-size:12px;color:var(--muted)}
button:focus-visible,a:focus-visible,textarea:focus-visible,summary:focus-visible,[tabindex]:focus-visible{outline:3px solid #1468c2;outline-offset:3px}
.app-shell.easy-read .context-card p,.app-shell.easy-read .detail-desc,.app-shell.easy-read #coachAdvice,.app-shell.easy-read .course-guide-hint,.app-shell.easy-read .ai-result,.app-shell.easy-read .level-report{font-size:18px;line-height:1.9}
.app-shell.easy-read .report-brief p,.app-shell.easy-read .step-alert{font-size:20px;line-height:1.8}
.app-shell.easy-read .btn,.app-shell.easy-read .course-btn{font-size:16px;min-height:48px}.app-shell.easy-read .card-head{font-size:15px}
.app-shell.high-contrast{--ink:#101010;--muted:#343434;--accent:#07563e;--line:#575757}
.app-shell.high-contrast .context-card,.app-shell.high-contrast .surface,.app-shell.high-contrast .ai-analysis,.app-shell.high-contrast .history-panel{background:#fff;border:2px solid #222}
.app-shell.high-contrast .muted,.app-shell.high-contrast .detail-note,.app-shell.high-contrast .context-card details p,.app-shell.high-contrast .safety-note,.app-shell.high-contrast .cue-meta{color:#333}
@media(max-width:760px){.context-grid{grid-template-columns:1fr}.context-card{padding:16px}}
@media(max-width:760px){.header{display:grid;gap:10px;padding:14px 0}.header-nav{gap:24px;font-size:13px}.header-nav a,.brand-caption,.health-label{white-space:nowrap}.health-item{flex-direction:column;align-items:flex-start;gap:4px}.intro{padding:16px 0 8px}.intro h1{font-size:23px}.cue-meta{font-size:11px}.step-alert{font-size:15px}}
</style></head>
<body><div class="app-shell" id="appShell">
<header class="header">
<a class="brand" href="#workspace" aria-label="OpenSignHand 训练工作台">
<span class="brand-mark"><svg width="25" height="27" viewBox="0 0 28 30" fill="none" aria-hidden="true"><path d="M8 17V9a2 2 0 014 0v7-11a2 2 0 014 0v11-9a2 2 0 014 0v10-5a2 2 0 014 0v9c0 5-3 8-8 8h-2c-3 0-5-2-7-5l-3-5a2 2 0 013-3l3 3" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg></span>
<span><span class="brand-name">随手表达</span><br><span class="brand-caption">OpenSignHand · AI + OPEN SOURCE</span></span></a>
<nav class="header-nav" aria-label="页面导航"><a class="active" href="#workspace">练习训练</a><a href="#communication">文字表达</a><a href="#analysis">训练报告</a></nav>
</header>
<div class="intro"><div><h1>看得懂动作，也能主动表达。</h1><p>选择课程 → 人工确认 → 观看示范 → 模仿练习 → 查看报告</p></div><div class="intro-note">端侧 AI · 开源机械平台 · 自主沟通</div></div>
<div class="readability-tools" aria-label="阅读辅助"><button type="button" id="easyRead" class="btn" aria-pressed="false">大字阅读</button><button type="button" id="highContrast" class="btn" aria-pressed="false">增强对比</button><a href="#communication">跳到文字沟通</a><span>支持键盘 Tab 选择、Enter 确认；不依赖声音提示。</span></div>
<div class="health-bar" aria-label="设备链路实时状态">
<div class="health-item"><span class="health-label">视觉识别</span><span id="healthVision" class="health-val unknown">未上报</span></div>
<div class="health-item"><span class="health-label">Titan 链路</span><span id="healthTitan" class="health-val unknown">未上报</span></div>
<div class="health-item"><span class="health-label">机械手状态</span><span id="healthMotion" class="health-val unknown">未上报</span></div>
<div class="health-item" title="Titan 端侧 AI（输入可信度参考）：辅助判断，非安全认证"><span class="health-label">端侧AI参考</span><span id="healthAiTrust" class="health-val unknown">未上报</span></div>
</div>
<section id="signPanel" class="panel">
<div id="workspace" class="workspace-heading"><h2>训练工作台</h2><span class="muted">电脑浏览器是学习者主界面，MaixCAM2 屏幕仅调试</span></div>
<div class="process-wrap"><div class="process-title">五步训练流转进度：</div><div class="process-bar">
<div id="step1" class="p-step active"><span class="p-step-name">1. 选择课程</span><span id="stepTag1" class="p-step-tag">[进行中]</span></div>
<div id="step2" class="p-step"><span class="p-step-name">2. 人工确认</span><span id="stepTag2" class="p-step-tag">[待进行]</span></div>
<div id="step3" class="p-step"><span id="step3Name" class="p-step-name">3. 参考动作示范</span><span id="stepTag3" class="p-step-tag">[待进行]</span></div>
<div id="step4" class="p-step"><span class="p-step-name">4. 学习者模仿</span><span id="stepTag4" class="p-step-tag">[待进行]</span></div>
<div id="step5" class="p-step"><span class="p-step-name">5. 完成评价</span><span id="stepTag5" class="p-step-tag">[待进行]</span></div>
</div></div>
<div class="main-grid">
<aside class="col-left surface">
<div class="card-heading"><h3>今日练习</h3><span class="section-index">01 / PRACTICE</span></div>
<div id="lessonDetailCard" class="lesson-detail">
<div class="detail-head"><span><span id="detailEmoji" class="emoji">✋</span><b id="detailTitle">请选择课程</b></span><span id="detailBadge" class="badge">基础手型</span></div>
<div id="detailDesc" class="detail-desc">选择一个手型，观看示范，再对着摄像头模仿。</div>
<a class="btn next-action" href="#expression">查看表达含义与交流情境</a>
<div class="detail-note muted">辅助动作原型，不代表完整标准手语；动态表达须按提示完成动作顺序与次数。</div>
</div>
<div class="level-box"><div class="level-label">选择组合课程</div><div class="level-buttons">
<button type="button" class="btn" data-level="beginner">初级 · 3 项</button>
<button type="button" class="btn" data-level="intermediate">中级 · 4 项</button>
<button type="button" class="btn" data-level="advanced">高级 · 6 项</button>
</div><div id="levelProgress" class="muted">每一项都需要人工确认，不会自动开始。</div></div>
<section id="courseGuide" class="course-guide" aria-label="分级训练下一步引导" hidden>
<div id="courseGuideTitle" class="course-guide-title" role="status" aria-live="polite">等待选择分级训练</div>
<div id="courseGuideHint" class="course-guide-hint">每项都需要人工确认开始。</div>
<ol id="courseSteps" class="course-steps" aria-label="本级课程路线"><li id="courseStep1" hidden></li><li id="courseStep2" hidden></li><li id="courseStep3" hidden></li><li id="courseStep4" hidden></li><li id="courseStep5" hidden></li><li id="courseStep6" hidden></li></ol>
<button type="button" id="levelNext" class="btn primary next-action" disabled hidden>进入下一项</button>
<button type="button" id="levelReselect" class="btn next-action" hidden>重新选择当前项</button>
<button type="button" id="levelReportJump" class="btn primary next-action" hidden>查看本级报告与 AI 建议</button>
</section>
<div id="signActions" class="actions"><button type="button" id="signStart" class="btn primary" disabled>人工确认开始</button><button type="button" id="signCancel" class="btn danger" disabled>取消训练</button></div>
<div class="request-hint">请求状态 · <span id="signMessage">等待选择课程</span></div>
<details class="course-library" open><summary>探索课程库 <span class="muted">13 项</span></summary>
<div class="cat-tabs"><button type="button" class="tab-btn active" data-tab="all">全部 (13)</button><button type="button" class="tab-btn" data-tab="basic">基础 (7)</button><button type="button" class="tab-btn" data-tab="daily">日常 (5)</button><button type="button" class="tab-btn" data-tab="emergency">应急 (1)</button></div>
<div class="course-grid">
<div id="card_basic_open_palm" class="ref-card" data-cat="basic">
<div class="card-head"><span class="emoji">✋</span><b>张开手掌</b></div>
<div class="card-desc">张开手掌：五指自然张开，掌心朝向摄像头；</div>
<button type="button" class="course-btn" data-lesson="basic_open_palm" aria-label="选择课程：张开手掌">选择练习</button>
</div>
<div id="card_basic_fist" class="ref-card" data-cat="basic">
<div class="card-head"><span class="emoji">✊</span><b>握拳</b></div>
<div class="card-desc">握拳：五指收拢，拇指自然覆盖或贴近弯曲手指；</div>
<button type="button" class="course-btn" data-lesson="basic_fist" aria-label="选择课程：握拳">选择练习</button>
</div>
<div id="card_basic_v_sign" class="ref-card" data-cat="basic">
<div class="card-head"><span class="emoji">✌</span><b>V 形手势</b></div>
<div class="card-desc">V 形手势：食指和中指伸直分开，其余手指弯曲。</div>
<button type="button" class="course-btn" data-lesson="basic_v_sign" aria-label="选择课程：V 形手势">选择练习</button>
</div>
<div id="card_basic_point" class="ref-card" data-cat="basic">
<div class="card-head"><span class="emoji">☝️</span><b>食指指向</b></div>
<div class="card-desc">食指伸直，其余手指收拢；练习基础形状，不自动推断词义。</div>
<button type="button" class="course-btn" data-lesson="basic_point" aria-label="选择课程：食指指向">选择练习</button>
</div>
<div id="card_basic_thumbs_up" class="ref-card" data-cat="basic">
<div class="card-head"><span class="emoji">👍</span><b>竖拇指</b></div>
<div class="card-desc">拇指伸展，其余手指收拢；含义需要结合情境确认。</div>
<button type="button" class="course-btn" data-lesson="basic_thumbs_up" aria-label="选择课程：竖拇指">选择练习</button>
</div>
<div id="card_basic_l_shape" class="ref-card" data-cat="basic">
<div class="card-head"><span class="emoji">𠃊</span><b>L 形</b></div>
<div class="card-desc">食指与拇指伸展成直角，其余手指收拢；不认证手指字母。</div>
<button type="button" class="course-btn" data-lesson="basic_l_shape" aria-label="选择课程：L 形手型">选择练习</button>
</div>
<div id="card_basic_ok_pinch" class="ref-card" data-cat="basic">
<div class="card-head"><span class="emoji">👌</span><b>OK／确认</b></div>
<div class="card-desc">拇指和食指形成捏合，其余手指伸展；不自动等同同意或标准手语词。</div>
<button type="button" class="course-btn" data-lesson="basic_ok_pinch" aria-label="选择课程：OK／确认">选择练习</button>
</div>
<div id="card_word_hello" class="ref-card" data-cat="daily">
<div class="card-head"><span class="emoji">👋</span><b>你好</b></div>
<div class="card-desc">按顺序完成“食指指向 → 竖拇指”，只摆竖拇指不能通过。</div>
<button type="button" class="course-btn" data-lesson="word_hello" aria-label="选择课程：你好">选择练习</button>
</div>
<div id="card_word_thanks" class="ref-card" data-cat="daily">
<div class="card-head"><span class="emoji">🙏</span><b>谢谢</b></div>
<div class="card-desc">其余手指收拢，拇指“伸直 → 弯曲 → 伸直 → 弯曲 → 伸直”，按屏幕步骤完成。</div>
<button type="button" class="course-btn" data-lesson="word_thanks" aria-label="选择课程：谢谢">选择练习</button>
</div>
<div id="card_signal_help" class="ref-card" data-cat="emergency">
<div class="card-head"><span class="emoji">🆘</span><b>求助信号</b></div>
<div class="card-desc">张开手掌，将拇指收入掌心，再用其余手指包住。参考 Signal for Help，不是通用手语词或自动报警。</div>
<button type="button" class="course-btn" data-lesson="signal_help" aria-label="选择课程：求助信号">选择练习</button>
</div>
<div id="card_word_no" class="ref-card" data-cat="daily">
<div class="card-head"><span class="emoji">☝️↔</span><b>拒绝／不</b></div>
<div class="card-desc">食指伸展并左右摆动两次；用于否定语境的演示动作原型。</div>
<button type="button" class="course-btn" data-lesson="word_no" aria-label="选择课程：拒绝／不">选择练习</button>
</div>
<div id="card_word_attention" class="ref-card" data-cat="daily">
<div class="card-head"><span class="emoji">☝️</span><b>请注意</b></div>
<div class="card-desc">食指连续弯曲提示两次；用于吸引注意的演示动作原型。</div>
<button type="button" class="course-btn" data-lesson="word_attention" aria-label="选择课程：请注意">选择练习</button>
</div>
<div id="card_word_like" class="ref-card" data-cat="daily">
<div class="card-head"><span class="emoji">🤟</span><b>喜欢／爱心</b></div>
<div class="card-desc">先展示 L 形，再由拇指与食指完成捏合，按顺序判定。</div>
<button type="button" class="course-btn" data-lesson="word_like" aria-label="选择课程：喜欢／爱心">选择练习</button>
</div>
</div>

</details>
</aside>
<div class="col-right surface camera-surface">
<div class="card-heading"><h3>实时标注画面</h3><span class="camera-label"><span class="camera-dot"></span> MAIXCAM2 / VISION</span></div>
<section class="next-cue" aria-label="当前任务引导"><div class="cue-meta"><span id="currentCoursePosition">课程项目：尚未选择</span><span id="currentTrainingPhase">训练阶段：等待选课</span></div><div class="cue-label">现在做什么</div><div id="stepAlert" class="step-alert" role="status" aria-live="polite">先选择组合课程或单项练习</div></section>
<div class="stream-box stream-wrap">
<img id="streamImg" src="/stream" alt="实时标注画面">
<div id="streamFallback" class="stream-fallback" style="display:none">
<svg class="empty-camera" viewBox="0 0 64 64" fill="none" aria-hidden="true"><rect x="8" y="17" width="48" height="36" rx="8" stroke="currentColor" stroke-width="1.5"/><path d="M23 17l4-7h10l4 7" stroke="currentColor" stroke-width="1.5"/><circle cx="32" cy="34" r="10" stroke="currentColor" stroke-width="1.5"/><path d="M14 23h5" stroke="currentColor" stroke-width="1.5"/></svg>
<div class="fallback-title">等待摄像头画面</div><div>实时画面暂不可用，训练控制未自动触发</div></div>
</div>
<div id="videoHud" class="video-hud"><div><b>课程：</b><span id="hudLesson">未选择</span></div><div><b>阶段：</b><span id="hudPhase">提示先选课程</span></div><div><b>实时识别：</b><span id="hudGesture">--</span></div></div>
<div class="stream-footnote"><span>请将整只手放入画面，保持手指清晰可见。</span><span>画面断开可刷新 · 不触发训练</span></div>
<section class="result-separation" aria-label="本次课程结果"><small>本次课程结果 · 与当前实时识别分开记录</small><strong id="courseOutcome">尚未完成课程</strong><small id="courseOutcomeDetail">课程通过后，移开手或实时识别变化不会撤销该结果。</small></section>
<div class="live-caption">当前实时识别 <span>画面与状态分别刷新，可能有时间差；下列数值不是课程通过记录。</span></div>
<section id="sequenceGuide" class="sequence-guide" hidden aria-label="连续动作分步引导">
<h4 id="sequenceModeTitle">连续动作分步引导</h4>
<div class="sequence-controls"><button id="sequencePreview" type="button" class="btn" aria-pressed="false">教学预览（不计成绩）</button><button id="sequenceFollow" type="button" class="btn">返回当前判定步骤</button></div>
<p id="sequenceStage" role="status"></p><p id="sequenceInstruction"></p>
<ol id="sequenceSteps" aria-label="动作顺序"></ol>
<div id="sequenceEvidence"><strong>本步图像条件（不是动作对错结论）</strong><div id="sequenceChecks"></div>
<progress id="sequenceHold" max="300" value="0" aria-label="本步已观察保持时间"></progress><p id="sequenceHoldText"></p><p id="sequenceHint"></p></div>
<div id="sequencePreviewControls" class="sequence-controls" hidden><button id="sequencePrev" type="button" class="btn">上一动作</button><button id="sequenceNext" type="button" class="btn">下一动作</button></div>
<div id="manualReviewControls" hidden><p class="muted">遮挡或复杂动作可能无法自动核实。可逐步看教学说明，再由操作者复核；这不是自动识别通过，也不是专业手语鉴定。</p><label><input id="manualReviewConsent" type="checkbox">我已核对教学说明，并确认自己完成了本课全部动作</label><div class="sequence-controls"><button id="manualReviewButton" type="button" class="btn" disabled>人工复核结束本课（不计自动通过）</button></div><p id="manualReviewNotice" role="status"></p></div>
<p class="muted">教学预览只翻看说明，翻页不参与评分、不确认步骤、不触发机械动作，也不暂停正在进行的课程计时。正式练习先退出预览；不舒服可取消课程。当前动作属于二维顺序原型，尚不是经专业核验的标准手语。</p>
</section>
<div class="live-metrics">
<div class="live-metric"><small>识别手型</small><strong id="gesture">--</strong></div>
<div class="live-metric"><small>识别置信度</small><strong id="confidence">--</strong></div>
<div class="live-metric"><small>当前识别稳定值</small><strong id="stable">--</strong></div>
<div class="live-metric"><small>当前识别状态</small><strong id="validity">--</strong></div>
</div>
<section class="coach-panel" aria-label="可解释手型反馈">
<div class="coach-head"><strong>实时手型教练 · 看懂哪里需要调整</strong><span class="badge">关键点几何参考</span></div>
<div id="fingerCoach" class="finger-chips"></div><div id="coachAdvice" role="status">进入模仿阶段后，依据手部关键点给出调整参考。</div>
<div class="muted">本地关键点几何反馈，非大模型猜测。漏检或切换时暂停保持，保留本轮已确认步骤；设备异常会重置，整体训练仍有超时限制。分步达标不证明整段动作连续。</div>
</section>
<details class="note-box"><summary>设备状态与安全边界</summary>
<div class="diagnostic-grid"><div class="status kv">
<span>当前课程</span><b id="lesson">未选择</b><span>训练阶段</span><span id="phase">正在读取设备状态…</span>
<span>机械动作</span><span id="motionVal">未上报</span><span>端侧AI参考</span><span id="aitrustVal">未上报</span><span>错误原因</span><span id="errorCode">无</span>
</div><div>
<details><summary>识别诊断（仅几何数值，不上传照片）</summary><div class="kv"><span>四指伸展</span><span id="fingerDebug">未上报</span><span>拇指伸展</span><span id="thumbDebug">未上报</span><span>候选手型</span><span id="candidateDebug">未上报</span></div><div class="muted">顺序为食指、中指、无名指、小指；不是识别准确率。</div></details>
<div class="safety-note">检测到手势不会自动开始，必须人工确认。<br>请求排队不代表机械手已动作或完成。<br>Titan 端侧 AI 仅为输入可信度辅助参考，非安全认证，不代表视觉手语置信度。<br>当前手语模式未向 Titan 旧视觉模型发送所需输入，“未就绪”不代表机械手故障。</div>
</div></div></details>
</div></div>
<div class="context-grid">
<section class="context-card" id="expression" aria-labelledby="meaningTitle">
<span class="context-kicker">01 / 理解与尊重</span><h2 id="meaningTitle">这次练习，想表达什么？</h2>
<div class="context-tags"><span id="meaningKind">表达情境讲解</span><span>不会自动翻译或触发动作</span></div>
<p id="meaningIntent">选择课程后，这里解释表达目的、交流情境和本项目能验证的范围。</p>
<p id="meaningExample">先询问对方偏好的交流方式：手语、文字或其他方式，再确认彼此是否理解。</p>
<p id="meaningBoundary" class="boundary">手型不等于词义。本项目不是完整手语翻译器；课程通过不能证明真实沟通能力。</p>
<button type="button" id="meaningCard" class="btn" disabled>把表达意图显示为大字</button>
<details><summary>学习说明与资料来源</summary><p id="meaningSourceNote">本页情境短文由项目编写，不是手语词典动作条目。正式手语学习应使用经核实的教材和教学资源。</p>
<p>手语包含手部动作、面部表情和身体位置；不同使用者偏好可能不同。文字卡只是可选通道，不适用于所有人。</p>
<p><a id="meaningSource" href="https://www.w3.org/WAI/media/av/sign-languages/" target="_blank" rel="noopener noreferrer">W3C WAI：手语与沟通方式说明</a> · <a href="https://www.moe.gov.cn/jyb_sjzl/ziliao/A19/201807/t20180725_343691.html" target="_blank" rel="noopener noreferrer">教育部：国家通用手语常用词表资料</a></p>
</details></section>
<section class="context-card" id="communication" aria-labelledby="communicationTitle">
<span class="context-kicker">02 / 我来表达</span><h2 id="communicationTitle">文字沟通卡 · 不用等识别通过</h2>
<p>由你点击选择，给身边的人看。仅在此浏览器显示，不保存卡片内容、不上传给 AI，也不控制机械手。</p>
<div class="communication-actions">
<button type="button" class="btn" data-communication="请用文字和我交流。">请用文字</button><button type="button" class="btn" data-communication="请慢一点，一次说一件事。">请慢一点</button><button type="button" class="btn" data-communication="我需要帮助，请先询问我需要什么。">我需要帮助</button><button type="button" class="btn" data-communication="我需要休息一下。">需要休息</button>
</div><details><summary>写自己的话（最多 80 字）</summary><label for="communicationInput">想让对方看到的文字</label><textarea id="communicationInput" class="communication-input" maxlength="160" placeholder="例如：我想喝水，请帮我拿一下。"></textarea><button type="button" id="communicationShow" class="btn">显示这句话</button></details>
<p id="communicationStatus" role="status">不必模仿指定手型，也可以表达需求；文字卡不是自动报警服务。</p>
<div id="communicationDisplay" class="communication-display" hidden tabindex="-1" role="region" aria-label="给对方看的文字"><strong id="communicationText"></strong><button type="button" id="communicationClose" class="btn">收起并清空</button></div>
</section></div>
<section id="analysis" class="analysis-section" aria-label="训练报告与成长档案">
<div class="section-heading"><div><div class="eyebrow">REFLECT &amp; IMPROVE</div><h2>这次练习，下次的起点。</h2></div><span class="muted">真实记录 · 针对性复练</span></div>
<div class="analysis-grid">
<section class="ai-analysis" aria-label="AI 训练分析">
<div class="ai-analysis-head"><strong>AI 训练分析 · 下次怎么练</strong><span id="levelAiBadge" class="ai-badge">待生成</span></div>
<p class="muted">基于实际课程记录生成练习参考，不参与识别评分或机械手控制。</p>
<div class="ai-metrics"><div class="ai-metric"><small>本次记录</small><strong id="levelAiRecorded">0 项</strong></div><div class="ai-metric"><small>课程判定达标</small><strong id="levelAiCompleted">0 项</strong></div><div class="ai-metric"><small>待复核项目</small><strong id="levelAiFocus">等待训练</strong></div></div>
<section class="report-brief" aria-label="逐项课程结果摘要"><h3>本轮结果 · 先看结论</h3><p id="reportOverview">完成课程后，显示每项结果与已保存的判定依据。</p><p class="muted">课程达标不是识别准确率；人工复核单独记录。</p></section>
<section class="report-brief" aria-label="下次练习重点"><h3>下次先练什么</h3><p id="reportNextPractice">先完成一项练习，再依据记录选择复练重点。</p><p class="muted">优先显示最多 3 项；完整记录和分析见下方展开内容。</p></section>
<section class="report-brief" aria-label="分析建议及来源"><h3>分析建议 · 来源可追溯</h3><p id="advicePreview">尚未请求分析建议。基础报告无需模型也可使用。</p></section>
<details class="report-evidence"><summary>展开逐项分析与证据说明</summary>
<div id="levelAiResult" class="ai-result">本次不足
完成至少一项课程后，这里显示规则归纳的不足。

证据局限
新动态课程按步骤判定二维动作序列，不再仅按结束关键帧评价。没有步骤记录的旧结果不是完整连续动作通过。网页轮询次数不是独立视频帧，也不是识别准确率。分析只上传已确认的匿名课程摘要，不含照片或关键点。

下次练习建议
点击“生成 AI 下次训练建议”后，模型参考会出现在这里。模型文字不改变课程判定，也不触发机械动作。</div></details>
<div class="report-actions"><button type="button" id="levelAiAdvice" class="btn primary" disabled>生成 AI 下次训练建议</button><button type="button" id="levelDownload" class="btn" disabled>下载本次报告</button></div>
<div id="levelAiStatus" class="muted">需在电脑启动本地 AI 代理。只有点击按钮才发送匿名课程摘要，不发送图像或关键点。</div>
<details class="report-evidence"><summary>查看完整训练记录（下载包含全部内容）</summary><pre id="levelReport" class="level-report" hidden></pre></details>
</section>
<section class="history-panel" aria-label="训练成长与复练">
<div class="ai-analysis-head"><strong>训练成长档案</strong><span class="section-index">02 / PROGRESS</span></div>
<p class="muted">可选保存最近 20 次匿名记录，仅留在此浏览器。不保存图像、关键点或 AI 原文；换浏览器或地址后不可恢复。</p>
<div class="history-actions"><button type="button" id="historyToggle" class="btn">开启本机记录</button><button type="button" id="historyClear" class="btn">清除本机记录</button></div>
<div id="historyStatus" class="muted">本机持久保存尚未开启。</div>
<div id="historySummary" class="history-summary">完成一项后可查看同项前后对照，暂无虚构训练数据。</div>
<button type="button" id="levelRemedial" class="btn remedial-btn" disabled>选择针对性复练 · 最多 3 项</button>
<div id="remedialSummary" class="muted" style="margin-top:8px">复练计划基于已记录项目，不会自动开始训练。</div>
<div class="muted" style="margin-top:8px">共用电脑请训练后清除。未开启保存时，刷新会丢失记录。</div>
</section></div>
<p class="muted" style="margin-top:12px">报告仅汇总实际收到的结果，不作医疗评估或标准手语能力认证。当前展示七种基础手型与六种日常／应急表达。连续动作按二维步骤原型评价，不判断身体位置或完整标准手语语义。</p>
</section></section>
<details class="panel compat"><summary>兼容功能：水瓶康复训练</summary><p>检测到稳定水瓶后，请手动点击开始。页面绝不会自动开始训练。</p><button type="button" id="start" class="btn" disabled>开始康复训练</button><div id="s" class="status">正在读取设备状态…</div></details>
<footer class="footer"><span>OpenSignHand / 开源人机协同手势训练原型</span><span>端侧感知 → 可解释反馈 → 训练记录 → 人工复练</span></footer>
</div>
<script>
(function(){
var b=document.getElementById('start'),
s=document.getElementById('s'),
p=document.getElementById('signPanel'),
sb=document.getElementById('signStart'),
signActions=document.getElementById('signActions'),
cb=document.getElementById('signCancel'),
stepAlert=document.getElementById('stepAlert'),
lesson=document.getElementById('lesson'),
phase=document.getElementById('phase'),
gesture=document.getElementById('gesture'),
confidence=document.getElementById('confidence'),
stable=document.getElementById('stable'),
validity=document.getElementById('validity'),
errorCode=document.getElementById('errorCode'),
message=document.getElementById('signMessage'),
fingerDebug=document.getElementById('fingerDebug'),
thumbDebug=document.getElementById('thumbDebug'),
candidateDebug=document.getElementById('candidateDebug'),
motionVal=document.getElementById('motionVal'),
streamImg=document.getElementById('streamImg'),
streamFallback=document.getElementById('streamFallback'),
videoHud=document.getElementById('videoHud'),
hudLesson=document.getElementById('hudLesson'),
hudPhase=document.getElementById('hudPhase'),
hudGesture=document.getElementById('hudGesture'),
courseOutcome=document.getElementById('courseOutcome'),
courseOutcomeDetail=document.getElementById('courseOutcomeDetail'),
lastLiveObservation=null,lastLiveObservationMono=null,
healthVision=document.getElementById('healthVision'),
healthTitan=document.getElementById('healthTitan'),
healthMotion=document.getElementById('healthMotion'),
healthAiTrust=document.getElementById('healthAiTrust'),
aitrustVal=document.getElementById('aitrustVal'),
lastAiTrustGen=null,
lastAiTrustMonoTime=null,
step1=document.getElementById('step1'),
step2=document.getElementById('step2'),
step3=document.getElementById('step3'),
step4=document.getElementById('step4'),
step5=document.getElementById('step5'),
stepTag1=document.getElementById('stepTag1'),
stepTag2=document.getElementById('stepTag2'),
stepTag3=document.getElementById('stepTag3'),
stepTag4=document.getElementById('stepTag4'),
stepTag5=document.getElementById('stepTag5'),
step3Name=document.getElementById('step3Name'),
detailEmoji=document.getElementById('detailEmoji'),
detailTitle=document.getElementById('detailTitle'),
detailBadge=document.getElementById('detailBadge'),
detailDesc=document.getElementById('detailDesc'),
inflight=false,
posting=false;
var levelProgress=document.getElementById('levelProgress'),
levelReport=document.getElementById('levelReport'),
levelNext=document.getElementById('levelNext'),
courseGuide=document.getElementById('courseGuide'),
courseGuideTitle=document.getElementById('courseGuideTitle'),
courseGuideHint=document.getElementById('courseGuideHint'),
courseSteps=document.getElementById('courseSteps'),
levelReselect=document.getElementById('levelReselect'),
levelReportJump=document.getElementById('levelReportJump'),
levelDownload=document.getElementById('levelDownload'),
levelAiAdvice=document.getElementById('levelAiAdvice'),
levelAiBadge=document.getElementById('levelAiBadge'),
levelAiRecorded=document.getElementById('levelAiRecorded'),
levelAiCompleted=document.getElementById('levelAiCompleted'),
levelAiFocus=document.getElementById('levelAiFocus'),
levelAiResult=document.getElementById('levelAiResult'),
levelAiStatus=document.getElementById('levelAiStatus'),
levelRun=null,
aiAdviceText='',
aiAdviceSource='',
aiAdviceReason='',
aiAdviceEpoch=0,
aiAdviceBusy=false,
aiNotice='',
currentSignState='IDLE';
var fingerCoach=document.getElementById('fingerCoach'),coachAdvice=document.getElementById('coachAdvice'),
historyToggle=document.getElementById('historyToggle'),historyClear=document.getElementById('historyClear'),
historyStatus=document.getElementById('historyStatus'),historySummary=document.getElementById('historySummary'),
levelRemedial=document.getElementById('levelRemedial'),remedialSummary=document.getElementById('remedialSummary'),
lastSignMono=null,courseHistory=[],historyEnabled=false,historyKey='opensignhand_course_history_v1';
var sequenceGuide=document.getElementById('sequenceGuide'),sequenceStage=document.getElementById('sequenceStage'),
sequenceModeTitle=document.getElementById('sequenceModeTitle'),sequenceInstruction=document.getElementById('sequenceInstruction'),
sequenceSteps=document.getElementById('sequenceSteps'),sequenceChecks=document.getElementById('sequenceChecks'),
sequenceEvidence=document.getElementById('sequenceEvidence'),sequenceHold=document.getElementById('sequenceHold'),
sequenceHoldText=document.getElementById('sequenceHoldText'),sequenceHint=document.getElementById('sequenceHint'),
sequencePreview=document.getElementById('sequencePreview'),sequenceFollow=document.getElementById('sequenceFollow'),
sequencePrev=document.getElementById('sequencePrev'),sequenceNext=document.getElementById('sequenceNext'),
sequencePreviewControls=document.getElementById('sequencePreviewControls'),
sequenceTeaching=false,sequencePreviewIndex=0,sequenceLesson=null,sequenceLast=null;
var manualReviewControls=document.getElementById('manualReviewControls'),manualReviewConsent=document.getElementById('manualReviewConsent'),
manualReviewButton=document.getElementById('manualReviewButton'),manualReviewNotice=document.getElementById('manualReviewNotice'),manualReviewRun=null;

if(streamImg){
streamImg.onerror=function(){
streamImg.style.display='none';
if(videoHud){videoHud.style.display='none';}
if(streamFallback){streamFallback.style.display='block';}
};
}

var STATUS_MAP={'IDLE':'提示先选课程','LESSON_SELECTED':'提示人工确认','DEMO_READY':'提示人工确认','DEMONSTRATING':'正在展示参考动作（约 3 秒）','IMITATING':'现在请对着摄像头模仿','COMPLETE':'完成','REVIEWED':'人工复核已记录（非自动通过）','TIMEOUT':'训练超时','CANCELLED':'训练已取消','FAULT':'训练故障','UNAVAILABLE':'训练暂不可用','DISABLED':'训练未启用'};
var GESTURE_MAP={'open_palm':'张开手掌','fist':'握拳','v_sign':'V 形手势','point':'食指指向','thumbs_up':'竖拇指','l_shape':'L 形手型','ok_pinch':'OK／确认','unknown':'未识别','none':'未识别'};
var LESSON_MAP={'basic_open_palm':'张开手掌','basic_fist':'握拳','basic_v_sign':'V 形手势','basic_point':'食指指向','basic_thumbs_up':'竖拇指','basic_l_shape':'L 形手型','basic_ok_pinch':'OK／确认','word_hello':'你好','word_thanks':'谢谢','signal_help':'求助信号','word_no':'拒绝／不','word_attention':'请注意','word_like':'喜欢／爱心'};
var LEVELS={
beginner:{name:'初级',lessons:['basic_open_palm','basic_fist','basic_v_sign']},
intermediate:{name:'中级',lessons:['basic_point','basic_thumbs_up','basic_l_shape','basic_ok_pinch']},
advanced:{name:'高级',lessons:['word_hello','word_thanks','word_no','word_attention','word_like','signal_help']}
};
var LESSON_INFO={
'basic_open_palm':{name:'张开手掌',emoji:'✋',cat:'基础手型',desc:'张开手掌：五指自然张开，掌心朝向摄像头；'},
'basic_fist':{name:'握拳',emoji:'✊',cat:'基础手型',desc:'握拳：五指收拢，拇指自然覆盖或贴近弯曲手指；'},
'basic_v_sign':{name:'V 形手势',emoji:'✌',cat:'基础手型',desc:'V 形手势：食指和中指伸直分开，其余手指弯曲。'},
'basic_point':{name:'食指指向',emoji:'☝️',cat:'基础手型',desc:'食指伸直，其余手指收拢；本课练习指向手型，不自动推断人称或词义。'},
'basic_thumbs_up':{name:'竖拇指',emoji:'👍',cat:'基础手型',desc:'拇指伸展，其余手指收拢；含义须结合交流情境确认。'},
'basic_l_shape':{name:'L 形手型',emoji:'L',cat:'基础手型',desc:'食指与拇指伸展成直角，其余手指收拢；本课仅练习形状，不认证手指字母。'},
'basic_ok_pinch':{name:'OK 捏合手型',emoji:'👌',cat:'基础手型',desc:'拇指和食指形成捏合，其余手指伸展；不自动等同“可以”或标准手语词。'},
'word_hello':{name:'你好',emoji:'👋',cat:'日常表达',desc:'按顺序完成“食指指向 → 竖拇指”，只摆竖拇指不能通过。'},
'word_thanks':{name:'谢谢',emoji:'🙏',cat:'日常表达',desc:'其余手指收拢，拇指“伸直 → 弯曲 → 伸直 → 弯曲 → 伸直”，按屏幕步骤完成。'},
'signal_help':{name:'求助信号',emoji:'🆘',cat:'求助情境',desc:'张开手掌，将拇指收入掌心，再用其余手指包住。参考 Signal for Help；不是通用手语词，也不是自动报警。'},
'word_no':{name:'拒绝／不',emoji:'☝️↔',cat:'日常表达',desc:'食指伸展并左右摆动两次；用于否定语境的演示动作原型。'},
'word_attention':{name:'请注意',emoji:'☝️',cat:'日常表达',desc:'食指连续弯曲提示两次；用于吸引注意的演示动作原型。'},
'word_like':{name:'喜欢／爱心',emoji:'🤟',cat:'日常表达',desc:'先展示 L 形，再由拇指与食指完成捏合，按顺序判定。'}
};
var REASON_MAP={
'ok':'无','none':'无','hand_not_found':'未检测到手','unknown_gesture':'未识别到有效手型',
'no_hand':'未检测到手','invalid_landmarks':'手部关键点无效','invalid_result':'识别结果无效',
'no_lesson':'尚未选择课程','unknown_lesson':'未知课程','manual_confirm_required':'需要人工确认',
'manual_review':'操作者人工复核，非自动通过','manual_review_recorded':'人工复核已记录','review_not_allowed':'当前不能人工复核，请检查课程阶段','review_expired':'本轮已超时，请重新选课',
'low_confidence':'识别置信度不足','wrong_gesture':'当前手型与目标不符','target_mismatch':'当前手型与目标不符','sequence_in_progress':'连续动作进行中',
'link_offline':'Titan 连接断开','vision_stale':'视觉数据已过期','timeout':'训练超时',
'cancelled':'训练已取消','invalid_state':'当前阶段不允许此操作','external_fault':'设备状态异常',
'fault':'设备状态异常','lesson_selected':'课程已选择','started':'训练已开始',
'not_started':'尚未开始','sign_busy':'训练正在进行','invalid_lesson':'无效课程',
'sign_disabled':'手语训练暂不可用','sign_unavailable':'手语训练暂不可用',
'titan_status_stale':'Titan 状态已过期','titan_link_offline':'Titan 连接断开',
'titan_vision_stale':'视觉状态已过期','titan_not_actionable':'当前状态不允许执行',
'titan_pose_not_ok':'Titan 姿态状态异常','titan_gate_unavailable':'Titan 安全门不可用','uart_degraded':'通信状态异常',
'mechanical_demo_unverified':'机械示范尚未验证','invalid_command':'无效请求',
'invalid_request':'无效请求','request_unavailable':'服务不可用','origin_denied':'跨域访问被拒绝',
'lesson_not_selected':'尚未选择课程','controller_interface':'训练控制器接口不可用',
'controller_rejected':'训练控制器拒绝请求','start_rejected':'开始请求被拒绝',
'demo_rejected':'示范请求被拒绝','cancel_rejected':'取消请求被拒绝',
'request_busy':'设备正忙，请稍后重试','queued_for_main':'请求已接收，等待设备处理',
'applied':'操作已生效','accepted':'操作已生效','rejected':'请求被拒绝',
'expired':'请求已过期，请重新操作','request_expired':'请求已过期，请重新操作','idle':'就绪','pending':'处理中','submitted':'已提交',
'ready_for_request':'就绪','no_request':'无请求','not_bottle':'未检测到水瓶',
'bottle_not_stable':'水瓶尚未稳定','bottle_confidence_low':'水瓶识别置信度不足',
'not_target_phase':'当前不在目标检测阶段','training_not_idle':'康复训练尚未空闲',
'train_busy':'康复训练正在进行','status_unavailable':'设备状态不可用','availability_unknown':'就绪状态未知',
'unavailable':'训练暂不可用','disabled':'训练未启用'
};
function getMonoTime(){return (typeof performance!=='undefined'&&performance.now)?performance.now():Date.now();}
function text(v,f){return v===null||v===undefined||v===''?f:String(v)}
function get(u){return fetch(u,{cache:'no-store'}).then(function(r){return r.json()})}
function mapGesture(v){if(!v||v==='--')return '--';var k=String(v).trim().toLowerCase();return GESTURE_MAP[k]||String(v);}
function mapLesson(v){if(v===null||v===undefined||v==='')return '未选择';var k=String(v).trim().toLowerCase();return LESSON_MAP[k]||String(v);}
function mapReason(v,f){if(v===null||v===undefined||v==='')return f!==undefined?f:'无';var k=String(v).trim().toLowerCase();return REASON_MAP[k]||String(v);}
function mapRequest(v){if(v===null||v===undefined||v==='')return '就绪';var k=String(v).trim().toLowerCase();return REASON_MAP[k]||String(v);}
function disableActions(){sb.disabled=true;cb.disabled=true;Array.prototype.forEach.call(document.querySelectorAll('[data-lesson]'),function(btn){btn.disabled=true;});}

function updateDetail(lid){
var info=LESSON_INFO[lid];
updateMeaning(lid);
if(sequenceLesson!==lid){sequenceLesson=lid;sequenceTeaching=false;sequencePreviewIndex=0;sequenceLast=null;renderSequence({lesson_id:lid});}
if(info){
if(detailEmoji)detailEmoji.textContent=info.emoji;
if(detailTitle)detailTitle.textContent='当前课程：'+info.name;
if(detailBadge)detailBadge.textContent=info.cat;
if(detailDesc)detailDesc.textContent=info.desc;
}
}

// Original situation explanations, not a sign-language dictionary or translation model.
// Each field is text only. Adding a lesson must include its meaning boundary.
var EXPRESSION_CONTEXT={
basic_open_palm:{intent:'练习让手部完整入镜，为后续动作做好准备。',example:'和伙伴练习前，先确认画面清楚、双方方便交流。',card:'我们先确认一下交流方式。'},
basic_fist:{intent:'练习手指收拢的基础形状，不把握拳解释成一个固定词。',example:'舒适地收拢即可；不舒服可以停止，不需要用力握紧。',card:'我需要休息一下。'},
basic_v_sign:{intent:'练习食指、中指分开形成 V 的形状。',example:'同一手势在不同场合可能有不同含义，交流时请向对方确认。',card:'请确认一下我的意思。'},
basic_point:{intent:'练习指向的基础形状；具体指谁、指什么需要上下文。',example:'要指向物品时，可同时出示物品名称，避免只凭手型猜意思。',card:'我想指的是这个，请帮我确认。'},
basic_thumbs_up:{intent:'练习竖拇指形状；认可等意思须由双方结合情境确认。',example:'对方给出帮助后，可明确用文字表达认可，不把模型标签当作同意。',card:'谢谢你的帮助。'},
basic_l_shape:{intent:'练习拇指与食指构成 L 的基础形状。',example:'不要据此学习国家通用手指字母拼写；不同体系的字母手形不能混用。',card:'请把名称写下来。'},
basic_ok_pinch:{intent:'练习拇指与食指捏合的形状，不自动代表承诺或同意。',example:'需要确认服务内容时，可用文字说清楚，而不是由识别结果代替确认。',card:'请让我先确认一下。'},
word_hello:{intent:'表达情境：开启交流、友好问候。',example:'初次见面：你好，请问你更喜欢用文字还是其他方式交流？',card:'你好，请问你希望用什么方式交流？'},
word_thanks:{intent:'表达情境：感谢具体的帮助。',example:'同伴帮忙拿取物品后：谢谢你帮我拿水。',card:'谢谢你的帮助。'},
word_no:{intent:'表达情境：清楚表达拒绝或暂时不需要。',example:'别人询问是否需要协助时：谢谢，我暂时不需要；请尊重我的选择。',card:'谢谢，我暂时不需要，请先询问我的意愿。'},
word_attention:{intent:'表达情境：礼貌地请对方注意并确认可以交流。',example:'开始说明需求前：请看这里，我们用文字确认一下。',card:'请看这里，我有话想和你说。'},
word_like:{intent:'表达情境：说明自己的喜好，而不是推断对方的感情。',example:'选择活动或物品时：我喜欢这个，也请问问我的选择。',card:'我喜欢这个，这是我的选择。'},
signal_help:{intent:'Signal for Help：请求对方安全地联系、了解所需支持。',example:'看到信号后，先在安全的情况下询问对方希望怎样获得支持，不擅自代替其决定。',card:'我需要帮助，请先询问我需要什么。'}
};
var selectedContext=null,cardOpener=null;
function updateMeaning(lid){
var context=EXPRESSION_CONTEXT&&Object.prototype.hasOwnProperty.call(EXPRESSION_CONTEXT,lid)?EXPRESSION_CONTEXT[lid]:null;
selectedContext=context;
var dynamic=lid&&lid.indexOf('word_')===0,help=lid==='signal_help';
var kind=help?'有来源的求助信号说明':dynamic?'表达情境 · 实验动作原型':'基础手型 · 不直接代表词义';
var boundary=help?'不是国家通用手语词，也不代表立即报警。本系统只练习二维动作，不判断危险、不联系任何人。':dynamic?'这节课的名称表示练习情境。当前动作组合是项目二维实验原型，尚未经专业核验为该词的标准手语打法。':'只验证有限手型，不判断语义、身体位置或面部表情，也不认证手指字母或交流能力。';
document.getElementById('meaningKind').textContent=context?kind:'表达情境讲解';
document.getElementById('meaningIntent').textContent=context?context.intent:'选择课程后，这里解释表达目的、交流情境和本项目能验证的范围。';
document.getElementById('meaningExample').textContent=context?context.example:'先询问对方偏好的交流方式：手语、文字或其他方式，再确认彼此是否理解。';
document.getElementById('meaningBoundary').textContent=context?boundary:'手型不等于词义。本项目不是完整手语翻译器；课程通过不能证明真实沟通能力。';
var source=document.getElementById('meaningSource');
source.href=help?'https://canadianwomen.org/signal-for-help/':'https://www.w3.org/WAI/media/av/sign-languages/';
source.textContent=help?'Canadian Women’s Foundation：Signal for Help 原始说明':'W3C WAI：手语与沟通方式说明';
document.getElementById('meaningSourceNote').textContent=help?'本项目以原创文字概述信号用途并链接原始说明，未转载图片或视频；不是手语词典。':'情境与示例由项目编写；下方资料解释手语的范围，不为本项目动作与词义的对应关系背书。';
document.getElementById('meaningCard').disabled=!context;
}
function showCommunication(value,opener){
var status=document.getElementById('communicationStatus');
var clean=String(value||'').trim(),letters=Array.from(clean);
// Invalid replacement must not leave the previous sentence presented as current intent.
document.getElementById('communicationDisplay').hidden=true;
document.getElementById('communicationText').textContent='';cardOpener=null;
if(!letters.length){status.textContent='请先选择一句话，或写下想表达的内容。';return;}
if(letters.length>80){status.textContent='内容超过 80 字，请缩短后再显示；尚未展示。';return;}
cardOpener=opener;document.getElementById('communicationText').textContent=clean;
var panel=document.getElementById('communicationDisplay');panel.hidden=false;
status.textContent='文字已显示；没有保存、上传或触发机械动作。共用电脑请使用后清空。';
if(panel.focus)panel.focus();
}
function closeCommunication(){
document.getElementById('communicationDisplay').hidden=true;
document.getElementById('communicationText').textContent='';
document.getElementById('communicationInput').value='';
document.getElementById('communicationStatus').textContent='已收起并清空。你可以选择新的表达。';
if(cardOpener&&cardOpener.focus)cardOpener.focus();cardOpener=null;
}
Array.prototype.forEach.call(document.querySelectorAll('[data-communication]'),function(btn){btn.onclick=function(){showCommunication(btn.getAttribute('data-communication'),btn);};});
document.getElementById('meaningCard').onclick=function(){if(selectedContext)showCommunication(selectedContext.card,this);};
document.getElementById('communicationShow').onclick=function(){showCommunication(document.getElementById('communicationInput').value,this);};
document.getElementById('communicationClose').onclick=closeCommunication;
if(document.addEventListener)document.addEventListener('keydown',function(event){if(event.key==='Escape'&&!document.getElementById('communicationDisplay').hidden){closeCommunication();}});
var easyRead=false,highContrast=false;
function updateReadability(){document.getElementById('appShell').className='app-shell'+(easyRead?' easy-read':'')+(highContrast?' high-contrast':'');}
document.getElementById('easyRead').onclick=function(){easyRead=!easyRead;this.setAttribute('aria-pressed',String(easyRead));this.textContent=easyRead?'恢复标准字号':'大字阅读';updateReadability();};
document.getElementById('highContrast').onclick=function(){highContrast=!highContrast;this.setAttribute('aria-pressed',String(highContrast));this.textContent=highContrast?'恢复标准对比':'增强对比';updateReadability();};
updateMeaning(null);

function post(u,payload){
posting=true;
disableActions();
return fetch(u,{method:'POST',headers:{'Content-Type':'application/json'},body:payload===null?'{}':JSON.stringify(payload)})
.then(function(r){return r.json()})
.then(function(x){
var st=mapRequest(x.state);
var rs=x.reason?'：'+mapReason(x.reason):'';
message.textContent=st+rs;
})
.catch(function(){message.textContent='请求失败，未触发训练'})
.then(function(){posting=false;r()})
}

function setAiBadge(label,state){
if(levelAiBadge){levelAiBadge.textContent=label;levelAiBadge.className='ai-badge'+(state?' '+state:'');}
}
var AI_REASON_TEXT={
evidence_conflict:'证据与记录冲突，未采用模型原文',
provider_timeout:'模型响应超时，未采用模型结果',
provider_unavailable:'模型服务不可用，未采用模型结果',
provider_response_invalid:'模型返回无法使用，未采用模型结果',
provider_response_too_large:'模型返回过长，未采用模型结果'
};
function adviceCodePoints(text){return Array.from(text).length;}
function acceptAdviceContract(result){
if(!result||typeof result!=='object'||Array.isArray(result))return null;
var keys=Object.keys(result);
if(keys.length!==3)return null;
var seen={};
for(var i=0;i<keys.length;i++)seen[keys[i]]=true;
if(!seen.advice||!seen.source||!seen.fallback_reason)return null;
var advice=result.advice;
if(typeof advice!=='string'||!advice.trim()||adviceCodePoints(advice)>800)return null;
if(result.source==='model'){
if(result.fallback_reason!==null)return null;
return {advice:advice,source:'model',reason:''};
}
if(result.source==='local'&&typeof result.fallback_reason==='string'&&Object.prototype.hasOwnProperty.call(AI_REASON_TEXT,result.fallback_reason)){
return {advice:advice,source:'local',reason:result.fallback_reason};
}
return null;
}
function clearAiAdvice(){
aiAdviceText='';aiAdviceSource='';aiAdviceReason='';aiNotice='';
var preview=document.getElementById('advicePreview');
if(preview)preview.textContent='尚未请求分析建议。基础报告无需模型也可使用。';
aiAdviceEpoch++;
}
function invalidateAdviceSelection(){
clearAiAdvice();setAiBadge('待生成','');
if(levelAiStatus)levelAiStatus.textContent='课程选择已变化，请按当前记录重新生成建议。';
renderLevelReport();
}
function adviceOriginLines(){
if(!aiAdviceText)return [];
var origin='建议来源：来源未记录。不能视为模型已联通。';
if(aiAdviceSource==='model')origin='建议来源：模型建议（仅供参考）。';
else if(aiAdviceSource==='local')origin='建议来源：本地规则建议（未采用模型结果）。原因：'+(AI_REASON_TEXT[aiAdviceReason]||'原因未记录')+'。';
return [origin,'该文字不改变课程判定，不触发机械动作。',aiAdviceText];
}

// This is an explanation of the existing 2-D pattern gates, not a second
// classifier or a motion command. Numbers are normalized image geometry.
var COACH_TARGETS={
basic_open_palm:{f:[.68,.68,.68,.68]},basic_fist:{f:[-.62,-.62,-.62,-.62]},
basic_v_sign:{f:[.72,.72,-.75,-.75],gap:.22},
basic_point:{f:[.72,-.62,-.62,-.62],thumb:-.52},
basic_thumbs_up:{f:[-.62,-.62,-.62,-.62],thumb:.55},
basic_l_shape:{f:[.72,-.62,-.62,-.62],thumb:.55},
basic_ok_pinch:{f:[-.68,.68,.68,.68],pinch:.42}
};
var COACH_FINAL={word_hello:'basic_thumbs_up',word_thanks:'basic_thumbs_up',
signal_help:'basic_fist',word_no:'basic_point',word_attention:'basic_point',word_like:'basic_ok_pinch'};
function coachFeedback(x){
var result={message:'进入模仿阶段后，依据手部关键点给出调整参考。',fingers:[]};
if(String(x.state||'').toUpperCase()!=='IMITATING')return result;
var err=String(x.recognition_error_code||x.error_code||'').toLowerCase();
if(x.link_online===false||/link_offline|vision_stale|invalid_landmarks|invalid_result/.test(err)){
result.message='视觉或连接状态异常，暂停手型建议；先检查设备与画面。';return result;}
if(err==='no_hand'||err==='hand_not_found'){
result.message='未检测到手：请让整只手进入画面，避免手指遮挡，先检查光照。';return result;}
var lid=x.lesson_id,target=Object.prototype.hasOwnProperty.call(COACH_TARGETS,lid)?COACH_TARGETS[lid]:
(Object.prototype.hasOwnProperty.call(COACH_FINAL,lid)?COACH_TARGETS[COACH_FINAL[lid]]:null),shape=x.shape_debug;
if(x.motion_progress){result.message='当前第 '+Math.min(x.motion_progress.completed_steps+1,x.motion_progress.total_steps)+'/'+x.motion_progress.total_steps+' 步：'+x.motion_progress.prompt+'；已确认 '+x.motion_progress.completed_steps+' 步。'+(x.motion_progress.feedback||'按提示慢慢切换，每步保持约 0.3 秒。');return result;}
if(!target||!shape||!Array.isArray(shape.finger_extension)||shape.finger_extension.length!==4||
!shape.finger_extension.every(function(v){return typeof v==='number'&&Number.isFinite(v)&&v>=0&&v<=1;})){
result.message='手指几何数据不足，无法指出具体薄弱手指；请检查关键点画面。';return result;}
var names=['食指','中指','无名指','小指'],adjust=[],missing=false;
function check(name,value,threshold){
var fold=threshold<0,bad=fold?value>-threshold:value<threshold;
var instruction=fold?'收拢':'伸展';
result.fingers.push({text:name+' '+value.toFixed(2)+' · '+(bad?'建议'+instruction:'几何接近目标'),adjust:bad});
if(bad)adjust.push(name+'的图像估计偏'+(fold?'伸展，请尝试收拢':'弯曲，请尝试伸展'));
}
for(var i=0;i<4;i++)check(names[i],shape.finger_extension[i],target.f[i]);
if(target.thumb!==undefined){
if(typeof shape.thumb_extension==='number'&&Number.isFinite(shape.thumb_extension)&&shape.thumb_extension>=0&&shape.thumb_extension<=1)check('拇指',shape.thumb_extension,target.thumb);
else missing=true;
}
if(target.gap!==undefined){
if(typeof shape.tip_gap!=='number'||!Number.isFinite(shape.tip_gap))missing=true;
else if(shape.tip_gap<target.gap)adjust.push('食指与中指的图像间距偏小，请分开两指');
}
if(target.pinch!==undefined){
if(typeof shape.thumb_index_gap!=='number'||!Number.isFinite(shape.thumb_index_gap))missing=true;
else if(shape.thumb_index_gap>target.pinch)adjust.push('拇指与食指的图像间距偏大，请尝试捏合');
}
result.message=(COACH_FINAL[lid]?'仅看结束关键帧：':'')+(adjust.length?adjust.join('；')+'。若与实际手型不符，请转正手掌并减少遮挡。':
'已上报的手指几何接近目标，请保持稳定；这不等于课程已完成。');
if(missing)result.message+=' 部分拇指或间距数据未上报，反馈不完整。';
return result;
}
function renderCoach(x){
var feedback=coachFeedback(x);
if(coachAdvice)coachAdvice.textContent=feedback.message;
if(fingerCoach){fingerCoach.textContent='';feedback.fingers.forEach(function(item){
var chip=document.createElement('span');chip.className='finger-chip'+(item.adjust?' adjust':'');
chip.textContent=item.text;fingerCoach.appendChild(chip);
});}
}

function boundedInt(v,max){return typeof v==='number'&&Number.isInteger(v)&&v>=0&&v<=max;}
function isDynamicLesson(lid){return LEVELS.advanced.lessons.indexOf(lid)>=0;}
function renderManualReview(x){
if(!manualReviewControls)return;
var allowed=isDynamicLesson(x.lesson_id)&&x.state==='IMITATING'&&x.can_review===true&&boundedInt(x.session_token,2147483647)&&x.session_token>0&&x.link_online===true;
var same=manualReviewRun&&manualReviewRun.lesson_id===x.lesson_id&&manualReviewRun.session_token===x.session_token;
if(!same||!allowed){manualReviewConsent.checked=false;manualReviewNotice.textContent='';}
manualReviewRun=allowed?{lesson_id:x.lesson_id,session_token:x.session_token}:null;
manualReviewControls.hidden=!allowed;
manualReviewButton.disabled=!allowed||posting||manualReviewConsent.checked!==true;
}
function validCompletionHold(row){return row.state==='COMPLETE'&&!isDynamicLesson(row.lesson_id)&&boundedInt(row.completion_stable_ms,600000)&&row.completion_stable_ms>=300;}
function cleanMotionProgress(v){
if(!v||v.scope!=='2d_sequence_prototype'||!boundedInt(v.completed_steps,6)||!boundedInt(v.total_steps,6)||
v.total_steps<1||v.completed_steps>v.total_steps||typeof v.complete!=='boolean'||
v.complete!==(v.completed_steps===v.total_steps))return null;
return {completed_steps:v.completed_steps,total_steps:v.total_steps,complete:v.complete,scope:'2d_sequence_prototype'};
}

// Explanatory labels only; the device remains the sole owner of stage gates.
var SEQUENCE_TITLES={word_hello:['伸出食指','切换竖拇指'],word_like:['摆出 L 形','拇指食指捏合'],
word_thanks:['伸直拇指','第一次弯拇指','第一次伸直','第二次弯拇指','第二次伸直'],
word_attention:['伸直食指','第一次弯食指','第一次伸直','第二次弯食指','第二次伸直'],
signal_help:['张开手掌','拇指收进掌心','四指握住拇指'],
word_no:['食指伸直居中','第一次摆向一侧','第一次摆向另一侧','第二次摆向一侧','第二次摆向另一侧','食指回中']};
function sequenceUnavailable(reason){
if(sequenceChecks)sequenceChecks.textContent='暂无可用的新图像条件；不是动作错误。';
if(sequenceHold){sequenceHold.value=0;sequenceHold.setAttribute('aria-valuetext','当前没有可用保持读数');}
if(sequenceHoldText)sequenceHoldText.textContent='本步保持：等待新读数';
if(sequenceHint)sequenceHint.textContent=reason;
}
function renderSequence(x){
var lid=x.lesson_id,titles=Object.prototype.hasOwnProperty.call(SEQUENCE_TITLES,lid)?SEQUENCE_TITLES[lid]:null;
if(!sequenceGuide)return;
sequenceGuide.hidden=!titles;if(!titles)return;
if(sequenceLesson!==lid){sequenceTeaching=false;sequencePreviewIndex=0;sequenceLesson=lid;}
sequenceLast=x;
var raw=x.motion_progress,m=cleanMotionProgress(raw);
if(m&&m.total_steps!==titles.length)m=null;
var done=m?m.completed_steps:0,index=sequenceTeaching?sequencePreviewIndex:Math.min(done,titles.length-1);
sequenceModeTitle.textContent=sequenceTeaching?'教学预览 · 不计成绩':'当前课程 · 分步判定';
sequencePreview.setAttribute('aria-pressed',sequenceTeaching?'true':'false');
sequenceEvidence.hidden=sequenceTeaching;sequencePreviewControls.hidden=!sequenceTeaching;
sequencePrev.disabled=index===0;sequenceNext.disabled=index===titles.length-1;
sequenceStage.textContent=(sequenceTeaching?'正在看教学':'当前判定')+'第 '+(index+1)+'/'+titles.length+' 步：'+titles[index]+(sequenceTeaching?'（翻页不会完成课程）':'；已确认 '+done+' 步');
var instructions=raw&&raw.step_instructions;
sequenceInstruction.textContent=Array.isArray(instructions)&&instructions.length===titles.length&&instructions.every(function(v){return typeof v==='string'&&v.length<=160;})?instructions[index]:'按动作名称逐步查看；设备未提供本步详细说明，请确认运行新版完整工程。';
sequenceSteps.textContent='';titles.forEach(function(title,i){var item=document.createElement('li');
item.textContent=title+(sequenceTeaching?(i===index?' · 正在查看':''):(i<done?' · 已确认':i===index&&(!m||!m.complete)?' · 当前':' · 等待'));
item.className=i===index?'active-step':!sequenceTeaching&&i<done?'step-done':'';sequenceSteps.appendChild(item);});
if(sequenceTeaching)return;
if(!m){sequenceUnavailable('设备未提供有效步骤记录；这里不推测你是否做错。');return;}
if(String(x.state||'').toUpperCase()!=='IMITATING'){sequenceUnavailable(x.state==='REVIEWED'?'本课已记录操作者人工复核；步骤数仍是自动检测确认部分，不计自动通过。':m.complete?'本次课程序列原型已达标；当前图像条件不用于撤销记录。':'当前未进入模仿；可先看教学，人工确认后按原课程流程练习。');return;}
var err=String(x.recognition_error_code||x.error_code||'').toUpperCase();
var expired=(lastLiveObservationMono!==null&&getMonoTime()-lastLiveObservationMono>=1500)||(lastSignMono!==null&&getMonoTime()-lastSignMono>=1500);
if(expired||x.recognition_fresh===false||x.link_online===false||/NO_HAND|HAND_NOT_FOUND|STALE|SDK_ERROR|INVALID|VISION_READ_FAILED/.test(err)){
sequenceUnavailable(err==='NO_HAND'||err==='HAND_NOT_FOUND'?'未检测到手：先完整入镜；不要为了标签改变已经正确的动作。':'画面或连接不可用，等待新证据，不保留旧条件亮灯。');return;}
var states=['WAITING','CHECKING','HOLDING','MISSING','RESET','COMPLETE'],checks=raw.checks;
if(states.indexOf(raw.observation_state)<0||!Array.isArray(checks)||checks.length>4||!checks.every(function(c){return c&&typeof c.label==='string'&&c.label.length<=48&&['met','unmet'].indexOf(c.state)>=0;})){
sequenceUnavailable('步骤条件未上报或格式无效，请先检查程序版本。');return;}
sequenceChecks.textContent=checks.length?checks.map(function(c){return (c.state==='met'?'已观察到：':'尚未观察到：')+c.label;}).join('\\n'):'本步尚未观察到新的有效图像；请按上方说明慢慢切换。';
var required=raw.required_hold_ms,held=raw.phase_hold_ms;
if(!boundedInt(required,15000)||required<1||!boundedInt(held,15000)){sequenceUnavailable('保持读数缺失；不能代替设备确认本步。');return;}
held=raw.observation_state==='HOLDING'?Math.min(held,required):0;
sequenceHold.max=required;sequenceHold.value=held;sequenceHold.setAttribute('aria-valuetext',held+' / '+required+' 毫秒');
sequenceHoldText.textContent='本步已观察保持 '+held+' / '+required+' 毫秒 · 看到下一步提示后再切换';
sequenceHint.textContent=typeof raw.feedback==='string'&&raw.feedback.length<=64?raw.feedback:'请先检查图像条件；估计不符不等于你的动作错误。';
}
if(sequencePreview)sequencePreview.onclick=function(){sequenceTeaching=true;sequencePreviewIndex=0;renderSequence(sequenceLast||{lesson_id:sequenceLesson});};
if(sequenceFollow)sequenceFollow.onclick=function(){sequenceTeaching=false;renderSequence(sequenceLast||{lesson_id:sequenceLesson});};
if(sequencePrev)sequencePrev.onclick=function(){if(sequenceTeaching&&sequencePreviewIndex>0){sequencePreviewIndex--;renderSequence(sequenceLast);}};
if(sequenceNext)sequenceNext.onclick=function(){if(sequenceTeaching&&sequenceLast&&SEQUENCE_TITLES[sequenceLast.lesson_id]&&sequencePreviewIndex<SEQUENCE_TITLES[sequenceLast.lesson_id].length-1){sequencePreviewIndex++;renderSequence(sequenceLast);}};
function validHistorySession(s){
if(!s||typeof s!=='object'||typeof s.id!=='string'||!/^[a-z0-9_-]{1,64}$/.test(s.id)||
!Object.prototype.hasOwnProperty.call(LEVELS,s.level)||!Array.isArray(s.plan)||s.plan.length<1||s.plan.length>6||
!Array.isArray(s.rows)||s.rows.length<1||s.rows.length>s.plan.length||!boundedInt(s.time,8640000000000000))return false;
if(s.plan.some(function(lid,i){return LEVELS[s.level].lessons.indexOf(lid)<0||s.plan.indexOf(lid)!==i;}))return false;
return s.rows.every(function(row,i){
if(!row||row.lesson_id!==s.plan[i]||['COMPLETE','REVIEWED','TIMEOUT','CANCELLED','FAULT'].indexOf(row.state)<0||
!boundedInt(row.duration_s,3600)||!(row.confidence==='未上报'||(typeof row.confidence==='string'&&/^\\d{1,3}%$/.test(row.confidence)&&parseInt(row.confidence,10)<=100))||
typeof row.error_code!=='string'||row.error_code.length>64||!row.samples)return false;
if(row.motion_progress!==undefined&&!cleanMotionProgress(row.motion_progress))return false;
if(row.state==='REVIEWED'&&(!isDynamicLesson(row.lesson_id)||row.error_code!=='MANUAL_REVIEW'||!cleanMotionProgress(row.motion_progress)||row.motion_progress.complete))return false;
if(row.completion_stable_ms!==undefined&&!validCompletionHold(row))return false;
var a=row.samples;
return ['observations','low_confidence','no_hand','wrong_gesture','vision_stale','max_stable_ms'].every(function(k){return boundedInt(a[k],k==='max_stable_ms'?600000:3600);})&&
['low_confidence','no_hand','wrong_gesture','vision_stale'].every(function(k){return a[k]<=a.observations;});
});
}
function cleanHistorySession(s){
return {id:s.id,level:s.level,plan:s.plan.slice(),time:s.time,rows:s.rows.map(function(row){
var a=row.samples,copy={lesson_id:row.lesson_id,state:row.state,duration_s:row.duration_s,confidence:row.confidence,
error_code:row.error_code,samples:{observations:a.observations,low_confidence:a.low_confidence,no_hand:a.no_hand,
wrong_gesture:a.wrong_gesture,vision_stale:a.vision_stale,max_stable_ms:a.max_stable_ms}};
var motion=cleanMotionProgress(row.motion_progress);if(motion)copy.motion_progress=motion;
if(validCompletionHold(row))copy.completion_stable_ms=row.completion_stable_ms;return copy;
})};
}
function loadCourseHistory(){
try{var raw=localStorage.getItem(historyKey);if(!raw)return;
if(raw.length>120000)throw new Error('oversize');
var saved=JSON.parse(raw);
if(!saved||saved.version!==1||saved.enabled!==true||!Array.isArray(saved.sessions)||saved.sessions.length>20||
!saved.sessions.every(validHistorySession)||saved.sessions.some(function(s,i){return saved.sessions.findIndex(function(v){return v.id===s.id;})!==i;}))throw new Error('invalid');
courseHistory=saved.sessions.map(cleanHistorySession);historyEnabled=true;
if(historyToggle)historyToggle.textContent='停止本机保存';
if(historyStatus)historyStatus.textContent='本机保存已开启，已恢复 '+courseHistory.length+' 次课程记录。';
}catch(e){if(historyStatus)historyStatus.textContent='本机记录不可读或格式无效，已忽略；不会影响训练。';}
}
function persistCourseHistory(){
if(!historyEnabled)return;
try{localStorage.setItem(historyKey,JSON.stringify({version:1,enabled:true,sessions:courseHistory}));
if(historyStatus)historyStatus.textContent='本机保存已开启：最近 '+courseHistory.length+' 次课程（仅此浏览器）。';
}catch(e){if(historyStatus)historyStatus.textContent='浏览器无法保存；本次只保留内存记录，刷新后可能丢失。';}
}
function archiveCourse(){
if(!levelRun||!levelRun.rows.length)return;
var s={id:levelRun.archiveId,level:levelRun.key,plan:levelRun.lessons,time:levelRun.archiveTime,rows:levelRun.rows};
if(!validHistorySession(s))return;
courseHistory=courseHistory.filter(function(old){return old.id!==s.id;});
courseHistory.push(cleanHistorySession(s));courseHistory=courseHistory.slice(-20);persistCourseHistory();
}
function remedialLessons(s){
if(!s)return [];
return s.rows.filter(function(row){
var a=row.samples,reason=String(row.error_code).toLowerCase();
if(row.state==='FAULT'||row.state==='CANCELLED'||/link_offline|vision_stale|invalid_landmarks|invalid_result/.test(reason))return false;
if(a.observations>0&&Math.max(a.no_hand,a.vision_stale)/a.observations>=.5)return false;
return row.state==='TIMEOUT'||(row.confidence.endsWith('%')&&parseInt(row.confidence,10)<70)||
(a.observations>=3&&Math.max(a.low_confidence,a.wrong_gesture)/a.observations>=.4);
}).sort(function(a,b){return (a.state==='TIMEOUT'?0:1)-(b.state==='TIMEOUT'?0:1);})
.slice(0,3).map(function(row){return row.lesson_id;});
}
function latestCourse(){return courseHistory.length?courseHistory[courseHistory.length-1]:null;}
function renderCourseHistory(){
var s=latestCourse(),lines=[];
if(s){
lines.push('最近记录：'+LEVELS[s.level].name+' · 已记录 '+s.rows.length+'/'+s.plan.length+' 项');
s.rows.forEach(function(row){
var old=null;
for(var i=courseHistory.length-2;i>=0&&!old;i--)old=courseHistory[i].rows.find(function(v){return v.lesson_id===row.lesson_id;});
if(!old){lines.push(mapLesson(row.lesson_id)+'：'+STATUS_MAP[row.state]+'（首次记录，尚无前后对照）');return;}
lines.push(mapLesson(row.lesson_id)+'：上次 '+STATUS_MAP[old.state]+' → 本次 '+STATUS_MAP[row.state]);
if(['FAULT','CANCELLED'].indexOf(old.state)<0&&['FAULT','CANCELLED'].indexOf(row.state)<0){
lines.push('  网页观察最长稳定 '+old.samples.max_stable_ms+' → '+row.samples.max_stable_ms+' 毫秒；耗时 '+old.duration_s+' → '+row.duration_s+' 秒');
}else lines.push('  含设备故障或取消，不比较动作表现。');
});
lines.push('仅同项记录对照；拍摄环境、观察次数可能不同，不据此认定学习效果或识别准确率。');
}else lines.push('暂无记录。完成一项后显示同项前后对照；未开启保存时刷新会丢失。');
if(historySummary)historySummary.textContent=lines.join('\\n');
var plan=remedialLessons(s);
if(remedialSummary)remedialSummary.textContent=plan.length?'建议复核/复练：'+plan.map(mapLesson).join(' → ')+'。点击只选课，每项仍需人工确认。':
'暂无可据以制定针对性复练的动作记录；若是断链、无手或视觉过期，请先排查设备和拍摄条件。';
if(levelRemedial)levelRemedial.disabled=!plan.length||posting||currentSignState==='DEMONSTRATING'||currentSignState==='IMITATING';
}

function processIssues(row){
var a=row.samples||{};
return (a.low_confidence||0)+(a.no_hand||0)+(a.wrong_gesture||0)+(a.vision_stale||0)>0;
}
function reportLimit(rows){
var dynamic=rows.filter(function(row){return isDynamicLesson(row.lesson_id);}),parts=[];
if(rows.some(function(row){return !isDynamicLesson(row.lesson_id);}))parts.push('静态课程完成表示目标手型达到课程保持门限；该记录不是完整连续动作通过或标准手语认证。');
if(dynamic.some(function(row){return row.motion_progress;}))parts.push('动态课程的步骤记录仅表示二维动作序列原型达标，允许中途暂停，不证明整段动作连续，不判断身体位置或完整标准手语语义。');
if(dynamic.some(function(row){return !row.motion_progress;}))parts.push('缺少步骤记录的旧动态结果只看结束关键帧，不是完整连续动作通过。');
parts.push('网页轮询读数可能重复或重叠，不是独立视频帧，也不是识别准确率；单次识别分数不代表整段表现。未采到非零稳定读数不等于没有保持。');
parts.push('分析只上传匿名课程摘要，不含照片或关键点；模型文字只作练习参考，不改变课程判定，不触发机械动作。');
return parts.join('');
}
function renderLevelReport(){
if(!levelRun||!levelReport)return;
var rows=levelRun.rows,passed=0,lines=[],weaknesses=[],nextSteps=[];
for(var i=0;i<rows.length;i++){if(rows[i].state==='COMPLETE')passed++;}
if(levelAiRecorded)levelAiRecorded.textContent=rows.length+' / '+levelRun.lessons.length+' 项';
if(levelAiCompleted)levelAiCompleted.textContent=passed+' 项';
if(levelAiFocus){var focusRows=rows.filter(function(row){return row.state!=='COMPLETE'||processIssues(row);});levelAiFocus.textContent=focusRows.length?focusRows.slice(0,3).map(function(row){return mapLesson(row.lesson_id);}).join('、'):'暂无明确项目';}
lines.push('OpenSignHand 本次分级训练记录');
lines.push('级别：'+levelRun.name+'；开始时间：'+levelRun.startedAt);
lines.push('进度：'+rows.length+'/'+levelRun.lessons.length+'；完成：'+passed+'；未完成：'+(rows.length-passed));
lines.push('完成率：'+(rows.length?Math.round(passed/levelRun.lessons.length*100):0)+'%（以全部计划项目为分母）');
var reviewed=rows.filter(function(row){return row.state==='REVIEWED';}).length;
if(reviewed)lines.push('人工复核记录：'+reviewed+' 项，不计入自动完成率；动作由操作者确认，设备未判定自动通过。');
for(var j=0;j<rows.length;j++){
var row=rows[j];
var stateText=STATUS_MAP[row.state]||row.state;
if(row.state==='COMPLETE')stateText+=row.motion_progress&&row.motion_progress.complete?'（二维动作序列原型通过）':isDynamicLesson(row.lesson_id)?'（关键帧记录，不是完整连续动作通过）':'（静态手型保持达标）';
lines.push((j+1)+'. '+mapLesson(row.lesson_id)+'：'+stateText+'；耗时 '+row.duration_s+' 秒；记录时识别分数 '+row.confidence+'；原因 '+mapReason(row.error_code,'无'));
if(row.state==='COMPLETE'&&!isDynamicLesson(row.lesson_id))lines.push('   课程通过时的保持值：'+(validCompletionHold(row)?row.completion_stable_ms+' 毫秒（课程判定记录）':'未记录；不能将缺失或网页的 0 值理解为没有保持。'));
if(row.motion_progress)lines.push('   '+(row.state==='REVIEWED'?'自动检测已确认步骤 ':'动作顺序进度 ')+row.motion_progress.completed_steps+'/'+row.motion_progress.total_steps+'；二维动作原型，非标准手语认证。');
if(row.samples&&row.samples.observations){lines.push('   模仿阶段网页轮询观察 '+row.samples.observations+' 次；低置信度 '+row.samples.low_confidence+' 次；未检测到手 '+row.samples.no_hand+' 次；手型不符 '+row.samples.wrong_gesture+' 次；视觉过期 '+row.samples.vision_stale+' 次；网页观察到的最长识别稳定值：'+(row.samples.max_stable_ms>0?row.samples.max_stable_ms+' 毫秒':'未采到非零读数')+'。');}
var lessonName=mapLesson(row.lesson_id),reason=String(row.error_code||'').toLowerCase();
if(row.state==='TIMEOUT'){
weaknesses.push(lessonName+'未在时限内完成；仅凭超时不能判断是手型错误还是识别/环境问题。');
nextSteps.push('优先复练'+lessonName+'，保持手掌完整入镜并观察实时识别结果，再决定是否调整手型或拍摄条件。');
}else if(row.state==='REVIEWED'){
weaknesses.push(lessonName+'已由操作者人工复核，自动检测未形成通过结果；不能据此评价动作能力。');
nextSteps.push('复练'+lessonName+'时逐步核对教学说明；遮挡阶段需人工观察，不必为迎合识别改变正确动作。');
}else if(row.state==='FAULT'||reason==='link_offline'||reason==='vision_stale'||reason==='invalid_landmarks'||reason==='no_hand'){
weaknesses.push(lessonName+'受到设备或视觉状态影响（'+mapReason(row.error_code,'原因未上报')+'），不能据此评价动作能力。');
nextSteps.push('复练'+lessonName+'前先检查连接、光照和手部关键点是否稳定。');
}else if(reason==='low_confidence'||reason==='wrong_gesture'||reason==='target_mismatch'){
weaknesses.push(lessonName+'结束时出现'+mapReason(row.error_code)+'；仍需结合实时画面核对手型。');
nextSteps.push('复练'+lessonName+'时对照课程提示，放慢动作并保持关键手指清晰可见。');
}else if(row.state==='COMPLETE'&&typeof row.confidence==='string'&&row.confidence.endsWith('%')&&parseInt(row.confidence,10)<70){
weaknesses.push(lessonName+'虽已完成，但结束时识别置信度低于 70%；单帧数值不能代表整段表现。');
nextSteps.push('复练'+lessonName+'，观察多次识别是否稳定，而非只看结束时的分数。');
}
var a=row.samples||{};
if(processIssues(row)){
var observed=[];
if(a.low_confidence>0)observed.push('低置信度 '+a.low_confidence+' 次');
if(a.no_hand>0)observed.push('未检测到手 '+a.no_hand+' 次');
if(a.wrong_gesture>0)observed.push('手型与目标不符 '+a.wrong_gesture+' 次');
if(a.vision_stale>0)observed.push('视觉过期 '+a.vision_stale+' 次');
weaknesses.push(lessonName+(row.state==='COMPLETE'?'已达标，但过程记录出现':'的过程记录出现')+observed.join('、')+'；这些是网页读数，不是独立做错次数，不能据此认定具体手指有问题。');
nextSteps.push('复练'+lessonName+'：'+(a.vision_stale>0?'先检查设备连接和画面更新；':'')+(a.no_hand>0?'先让整只手完整入镜，检查遮挡与光照；':'')+(a.low_confidence>0||a.wrong_gesture>0?'对照课程图示摆正手形，再短时重复并观察稳定识别。':'确认检测持续后再重复动作。'));
}
}
if(rows.length<levelRun.lessons.length)lines.push('本次课程尚未完成全部项目，以上为阶段性记录。');
var gapLines=[],nextLines=[];
if(weaknesses.length){for(var k=0;k<weaknesses.length;k++)gapLines.push('• '+weaknesses[k]);}
else gapLines.push(rows.length?'本次记录中没有明确的失败或低置信度项目；现有终态数据不足以判断更细的手型弱项。':'尚无已完成项目记录，无法判断薄弱项。');
if(nextSteps.length){for(var n=0;n<nextSteps.length;n++)nextLines.push('• '+nextSteps[n]);}
else nextLines.push(rows.length?'复练本级动作，观察多次识别与保持时间是否稳定。':'先完成至少一项课程，再依据实际结果制定针对性建议。');
var limitText=reportLimit(rows);
lines.push('本次不足：');
for(var g=0;g<gapLines.length;g++)lines.push(gapLines[g]);
lines.push('证据局限：');
lines.push('• '+limitText);
lines.push('下次练习建议：');
for(var s=0;s<nextLines.length;s++)lines.push(nextLines[s]);
var originLines=adviceOriginLines();
// Compact reading layer only; the complete evidence remains in the download.
var overview=document.getElementById('reportOverview'),practice=document.getElementById('reportNextPractice'),advicePreview=document.getElementById('advicePreview');
if(overview)overview.textContent=rows.length?rows.map(function(row){
var outcome=row.state==='COMPLETE'?'课程达标':row.state==='REVIEWED'?'人工复核（非自动通过）':(STATUS_MAP[row.state]||'未形成结果');
var evidence=row.motion_progress?'步骤 '+row.motion_progress.completed_steps+'/'+row.motion_progress.total_steps:row.state==='COMPLETE'&&validCompletionHold(row)?'通过时保持 '+row.completion_stable_ms+' 毫秒':'';
return mapLesson(row.lesson_id)+' · '+outcome+(evidence?' · '+evidence:'');
}).join('\\n'):'尚无课程结果；这是进行中的记录。';
if(practice){
var priorities=rows.filter(function(row){return row.state!=='COMPLETE'||processIssues(row);}).slice(0,3);
practice.textContent=priorities.length?priorities.map(function(row){
var a=row.samples||{},task=row.state==='REVIEWED'?'按教学说明逐步复练，遮挡步骤由人观察确认。':row.state==='FAULT'||a.vision_stale>0?'先检查设备连接和画面更新，再开始练习。':a.no_hand>0?'先让整只手完整入镜；检测持续后再按步骤练习。':isDynamicLesson(row.lesson_id)?'跟随当前步骤提示，确认后再切换到下一动作。':'对照课程手型，短时重复并观察保持结果。';
return mapLesson(row.lesson_id)+'：'+task;
}).join('\\n'):rows.length?'本轮暂无明确复练重点。可重复本级课程，观察下一次记录。':'先完成一项练习，再依据记录选择复练重点。';
}
if(advicePreview)advicePreview.textContent=originLines.length?originLines.join('\\n'):aiNotice||'尚未请求分析建议。基础报告无需模型也可使用。';
for(var o=0;o<originLines.length;o++)lines.push(originLines[o]);
if(aiNotice)lines.push(aiNotice);
lines.push('说明：数据仅来自本次网页实际接收到的设备状态；不作医疗评估或标准手语能力认证。');
levelReport.textContent=lines.join('\\n');
if(levelAiResult){
var card=['本次不足'];
for(var c=0;c<gapLines.length;c++)card.push(gapLines[c]);
card.push('证据局限');card.push(limitText);card.push('下次练习建议');
for(var d=0;d<nextLines.length;d++)card.push(nextLines[d]);
for(var o2=0;o2<originLines.length;o2++)card.push(originLines[o2]);
if(aiNotice)card.push(aiNotice);
levelAiResult.textContent=card.join('\\n');
}
levelReport.hidden=false;
if(levelDownload)levelDownload.disabled=rows.length===0;
if(levelAiAdvice)levelAiAdvice.disabled=rows.length===0||aiAdviceBusy;
}
function renderCourseGuide(x,stKey){
var active=levelRun&&!levelRun.stopped;
if(courseGuide)courseGuide.hidden=!active;
if(levelNext)levelNext.hidden=true;
if(levelReselect)levelReselect.hidden=true;
if(levelReportJump)levelReportJump.hidden=true;
sb.hidden=false;sb.textContent='人工确认开始';
if(signActions)signActions.hidden=Boolean(active&&levelRun.recorded);
if(!active)return '';
var expected=levelRun.lessons[levelRun.index],name=mapLesson(expected),count=levelRun.lessons.length;
var position=(levelRun.index+1)+'/'+count,matched=x&&x.lesson_id===expected,title='',hint='',banner='';
for(var i=0;i<6;i++){
var chip=document.getElementById('courseStep'+(i+1)),lid=levelRun.lessons[i];
if(!chip)continue;
chip.hidden=!lid;if(!lid)continue;
var row=levelRun.rows.find(function(item){return item.lesson_id===lid;}),kind=row?(row.state==='COMPLETE'?'passed':'recorded'):(i===levelRun.index?'current':'');
var label=row?(row.state==='COMPLETE'?'已完成':row.state==='REVIEWED'?'人工复核·非自动通过':'未完成·已记录'):(i===levelRun.index?'当前项':'未开始');
chip.className=kind;chip.textContent=(i+1)+'. '+mapLesson(lid)+' · '+label;
chip.setAttribute('aria-current',!row&&i===levelRun.index?'step':'false');
}
if(levelRun.recorded){
sb.hidden=true;sb.disabled=true;
var row=levelRun.rows[levelRun.rows.length-1],outcome=row&&row.state==='COMPLETE'?'已完成':(STATUS_MAP[row&&row.state]||'已记录');
if(levelRun.index+1<count){
var nextName=mapLesson(levelRun.lessons[levelRun.index+1]);
title=name+' '+outcome+' · '+position;
hint='下一项：'+nextName+'。点击下方“下一项”按钮选课，再点击“人工确认开始”。不会自动启动训练。';
banner=name+' '+outcome+'；下一项：'+nextName+'，请点击课程引导区的“下一项”按钮。';
if(levelNext){levelNext.hidden=false;levelNext.disabled=posting;levelNext.textContent='下一项：'+nextName+'（'+(levelRun.index+2)+'/'+count+'）';}
}else{
var passed=levelRun.rows.filter(function(item){return item.state==='COMPLETE';}).length;
title=levelRun.name+'本轮训练已结束 · 达标 '+passed+'/'+count;
hint='全部项目已记录。点击“查看本级报告与 AI 建议”，查看本次不足、生成建议或下载报告。未达标项目可在报告区选择复练。';
banner='本级训练已结束；请查看报告与 AI 下次训练建议。';
if(levelReportJump){levelReportJump.hidden=false;levelReportJump.disabled=false;}
}
}else if(!matched){
sb.disabled=true;title='第 '+position+' 项：'+name;
hint=posting?'正在选择课程，请稍候；尚未开始训练。':'等待设备确认当前课程。如迟迟没有更新，点击“重新选择当前项”；这只选课，不会开始训练。';
if(levelReselect){levelReselect.hidden=posting;levelReselect.disabled=posting;levelReselect.textContent='重新选择：'+name;}
}else if(stKey==='DEMONSTRATING'){
title='第 '+position+' 项：观看'+name+'示范';hint='先看参考示范，待页面提示“请模仿”后，再对着摄像头做动作。';
}else if(stKey==='IMITATING'){
title='第 '+position+' 项：现在模仿'+name;hint=LESSON_INFO[expected].desc+' 完成后会出现“下一项”按钮，无需去课程库找。';
}else if(stKey==='LESSON_SELECTED'||stKey==='DEMO_READY'){
title='第 '+position+' 项：准备练习'+name;
hint=x.can_start===true?'请点击下方“人工确认开始：'+name+'”。仅摆出手形不会自动开始。':'当前暂不能开始，请查看请求状态和设备连接；就绪后按钮会亮起。';
sb.textContent='人工确认开始：'+name;
banner='第 '+position+' 项：'+name+' · 请先人工确认开始';
}else{
title='第 '+position+' 项：'+name;hint='当前项目尚无完整结果，请查看设备状态；不会自动跳过或启动下一项。';
}
if(courseGuideTitle)courseGuideTitle.textContent=title;
if(courseGuideHint)courseGuideHint.textContent=hint;
return banner;
}
function updateLevelRun(x,stKey){
if(!levelRun||levelRun.stopped)return;
var expected=levelRun.lessons[levelRun.index];
if(x.lesson_id!==expected)return;
if(stKey==='DEMONSTRATING'||stKey==='IMITATING'){
if(!levelRun.seenActive){levelRun.seenActive=true;levelRun.itemStart=getMonoTime();}
if(stKey==='IMITATING'&&!levelRun.recorded){
var samples=levelRun.samples,recognitionError=String(x.recognition_error_code||x.error_code||'').toUpperCase();
var sessionError=String(x.session_error_code||'').toUpperCase();
samples.observations=Math.min(3600,samples.observations+1);
// A bent transition can be UNKNOWN to the static classifier while matching
// a dynamic phase. Do not count it as a failed static-shape observation.
if(recognitionError==='LOW_CONFIDENCE'&&!x.motion_progress)samples.low_confidence=Math.min(3600,samples.low_confidence+1);
if(recognitionError==='NO_HAND'||recognitionError==='HAND_NOT_FOUND')samples.no_hand=Math.min(3600,samples.no_hand+1);
if(recognitionError==='WRONG_GESTURE'||recognitionError==='TARGET_MISMATCH'||sessionError==='WRONG_GESTURE'||sessionError==='TARGET_MISMATCH')samples.wrong_gesture=Math.min(3600,samples.wrong_gesture+1);
if(recognitionError==='VISION_STALE')samples.vision_stale=Math.min(3600,samples.vision_stale+1);
if(typeof x.stable_ms==='number'&&x.stable_ms>=0)samples.max_stable_ms=Math.min(600000,Math.max(samples.max_stable_ms,Math.round(x.stable_ms)));
}
}
if(levelRun.seenActive&&!levelRun.recorded&&
(stKey==='COMPLETE'||stKey==='REVIEWED'||stKey==='TIMEOUT'||stKey==='CANCELLED'||stKey==='FAULT')){
levelRun.rows.push({lesson_id:expected,state:stKey,
duration_s:Math.max(0,Math.round((getMonoTime()-levelRun.itemStart)/1000)),
confidence:stKey==='COMPLETE'&&typeof x.course_confidence==='number'&&x.course_confidence>=0&&x.course_confidence<=1?Math.round(x.course_confidence*100)+'%':typeof x.confidence==='number'?Math.round(x.confidence*100)+'%':'未上报',
error_code:(stKey==='COMPLETE'||stKey==='REVIEWED')&&typeof x.session_error_code==='string'?x.session_error_code:x.error_code||x.reason||'',samples:Object.assign({},levelRun.samples)});
var savedRow=levelRun.rows[levelRun.rows.length-1];
if(stKey==='COMPLETE'&&!isDynamicLesson(expected)&&boundedInt(x.course_stable_ms,600000)&&x.course_stable_ms>=300)savedRow.completion_stable_ms=x.course_stable_ms;
var savedMotion=cleanMotionProgress(x.motion_progress);if(savedMotion)levelRun.rows[levelRun.rows.length-1].motion_progress=savedMotion;
if(aiAdviceText||aiAdviceSource||aiNotice){clearAiAdvice();if(levelAiStatus)levelAiStatus.textContent='训练记录已更新，请重新生成 AI 建议。';}
setAiBadge('待生成','');
levelRun.recorded=true;
archiveCourse();
renderLevelReport();
}
if(levelProgress)levelProgress.textContent=levelRun.name+' · 已记录 '+levelRun.rows.length+'/'+levelRun.lessons.length+' 项';
if(levelNext)levelNext.disabled=posting||!levelRun.recorded||levelRun.index+1>=levelRun.lessons.length;
renderCourseHistory();
}

function updateProcessBar(stKey, hasLesson, isRunning, isCompleted, sequenceComplete){
if(step3Name){
step3Name.textContent=isRunning?'3. 机械手示范':'3. 参考动作示范';
}
if(step1){
step1.className=hasLesson?'p-step done':'p-step active';
if(stepTag1)stepTag1.textContent=hasLesson?'[已完成]':'[待选课]';
}
if(step2){
if(stKey==='LESSON_SELECTED'||stKey==='DEMO_READY'){
step2.className='p-step active';
if(stepTag2)stepTag2.textContent='[待确认]';
}else if(stKey==='DEMONSTRATING'||stKey==='IMITATING'||stKey==='COMPLETE'||stKey==='REVIEWED'){
step2.className='p-step done';
if(stepTag2)stepTag2.textContent='[已确认]';
}else{
step2.className='p-step';
if(stepTag2)stepTag2.textContent='[待进行]';
}
}
if(step3){
if(stKey==='DEMONSTRATING'){
step3.className='p-step active';
if(stepTag3)stepTag3.textContent=isRunning?'[机械动作中]':'[示范进行中]';
}else if(stKey==='IMITATING'||stKey==='COMPLETE'||stKey==='REVIEWED'){
step3.className='p-step done';
if(stepTag3)stepTag3.textContent=isCompleted?'[机械动作完成]':'[示范已结束]';
}else{
step3.className='p-step';
if(stepTag3)stepTag3.textContent='[待进行]';
}
}
if(step4){
if(stKey==='IMITATING'){
step4.className='p-step active';
if(stepTag4)stepTag4.textContent='[模仿进行中]';
}else if(stKey==='COMPLETE'){
step4.className='p-step done';
if(stepTag4)stepTag4.textContent=sequenceComplete?'[动作序列原型达标]':'[课程门限达标]';
}else if(stKey==='REVIEWED'){
step4.className='p-step';
if(stepTag4)stepTag4.textContent='[操作者复核，非自动达标]';
}else{
step4.className='p-step';
if(stepTag4)stepTag4.textContent='[待进行]';
}
}
if(step5){
if(stKey==='COMPLETE'){
step5.className='p-step done';
if(stepTag5)stepTag5.textContent='[本次课程结果已保存]';
}else if(stKey==='REVIEWED'){
step5.className='p-step';
if(stepTag5)stepTag5.textContent='[人工复核已记录]';
}else if(stKey==='TIMEOUT'){
step5.className='p-step terminal-timeout';
if(stepTag5)stepTag5.textContent='[训练超时]';
}else if(stKey==='CANCELLED'){
step5.className='p-step terminal-cancel';
if(stepTag5)stepTag5.textContent='[训练已取消]';
}else if(stKey==='FAULT'){
step5.className='p-step terminal-fault';
if(stepTag5)stepTag5.textContent='[训练故障]';
}else{
step5.className='p-step';
if(stepTag5)stepTag5.textContent='[待评价]';
}
}
}

function showSign(x){
lastSignMono=getMonoTime();
var live=x;
if(typeof x.recognition_observed_ms==='number'&&Number.isInteger(x.recognition_observed_ms)&&x.recognition_observed_ms>=0&&x.recognition_observed_ms!==lastLiveObservation){lastLiveObservation=x.recognition_observed_ms;lastLiveObservationMono=getMonoTime();}
var liveStale=x.recognition_fresh===false||(lastLiveObservationMono!==null&&getMonoTime()-lastLiveObservationMono>=1500);
if(liveStale){live=Object.assign({},x,{gesture_id:'UNKNOWN',confidence:null,stable_ms:0,valid:false,error_code:'VISION_STALE',recognition_error_code:'VISION_STALE'});}
var liveError=String(live.recognition_error_code||live.error_code||'').toUpperCase();
var liveUnavailable=['VISION_READ_FAILED','INVALID_LANDMARKS','INVALID_RESULT','SDK_ERROR'].indexOf(liveError)>=0;
if(liveUnavailable){live=Object.assign({},live,{gesture_id:'UNKNOWN',confidence:null,stable_ms:0,valid:false});}
if(liveError==='NO_HAND'||liveError==='HAND_NOT_FOUND'){live=Object.assign({},live,{gesture_id:'UNKNOWN',confidence:null,stable_ms:0,valid:false});}
renderCoach(live);
renderSequence(live);
var enabled=!(x.state==='disabled'||x.reason==='sign_disabled');p.hidden=!enabled;
Array.prototype.forEach.call(document.querySelectorAll('[data-lesson]'),function(btn){btn.disabled=posting;});
if(!enabled){renderManualReview({});sb.disabled=true;cb.disabled=true;return;}
var stKey=String(x.state||'').toUpperCase();
currentSignState=stKey;
renderManualReview(x);
if(courseOutcome){
courseOutcome.className=stKey==='COMPLETE'?'passed':['TIMEOUT','CANCELLED','FAULT'].indexOf(stKey)>=0?'incomplete':'';
if(stKey==='COMPLETE'){
var sequence=cleanMotionProgress(x.motion_progress);
courseOutcome.textContent=sequence&&sequence.complete?'本次课程已通过 · 动作序列 '+sequence.completed_steps+'/'+sequence.total_steps:'本次课程已通过 · 课程门限达标';
var evidence=x.course_gesture_id?'通过时识别：'+mapGesture(x.course_gesture_id)+'。':'';
if(!isDynamicLesson(x.lesson_id)&&boundedInt(x.course_stable_ms,600000)&&x.course_stable_ms>=300)evidence+='通过时保持 '+x.course_stable_ms+' 毫秒。';
if(courseOutcomeDetail)courseOutcomeDetail.textContent=evidence+'当前识别变化或未检测到手，不撤销本次通过结果；不代表标准手语认证。';
}else if(stKey==='REVIEWED'){
courseOutcome.textContent='本次课程：人工复核已记录 · 非自动通过';
if(courseOutcomeDetail)courseOutcomeDetail.textContent='动作由操作者确认；自动步骤进度另行保留，不增加自动达标数量，不代表专业鉴定。';
}else{
courseOutcome.textContent=stKey==='TIMEOUT'?'本次课程未通过 · 超时':stKey==='CANCELLED'?'本次课程已取消':stKey==='FAULT'?'本次课程因故障中止':'尚未完成课程';
if(courseOutcomeDetail)courseOutcomeDetail.textContent='本区显示课程判定；当前手型与稳定值见下方实时识别。';
}}
updateLevelRun(x,stKey);
renderCourseHistory();
var prompt=STATUS_MAP[stKey];
var coursePosition=document.getElementById('currentCoursePosition'),trainingPhase=document.getElementById('currentTrainingPhase');
if(coursePosition)coursePosition.textContent=levelRun&&!levelRun.stopped?levelRun.name+'课程 · 第 '+(levelRun.index+1)+'/'+levelRun.lessons.length+' 项：'+mapLesson(levelRun.lessons[levelRun.index]):'单项练习：'+mapLesson(x.lesson_id);
if(trainingPhase)trainingPhase.textContent='训练阶段：'+(STATUS_MAP[stKey]||'等待选课');
if(!x.lesson_id&&(stKey==='IDLE'||!stKey)){prompt='提示先选课程';}
else if(!prompt){prompt=mapReason(x.state,'不可用');}
if(stKey==='IMITATING'&&x.motion_progress){prompt='当前第 '+Math.min(x.motion_progress.completed_steps+1,x.motion_progress.total_steps)+'/'+x.motion_progress.total_steps+' 步：'+x.motion_progress.prompt+'（已确认 '+x.motion_progress.completed_steps+' 步）';if(x.motion_progress.feedback)prompt+=' · '+x.motion_progress.feedback;}
stepAlert.textContent=prompt;
phase.textContent=prompt;
lesson.textContent=x.lesson_name?text(x.lesson_name,'未选择'):mapLesson(x.lesson_id);
gesture.textContent=liveStale?'识别已过期':liveUnavailable?'识别暂不可用':liveError==='NO_HAND'||liveError==='HAND_NOT_FOUND'?'未检测到手':mapGesture(live.gesture_id);
confidence.textContent=typeof live.confidence==='number'?Math.round(live.confidence*100)+'%':'--';
if(hudLesson){hudLesson.textContent=lesson.textContent;}
if(hudPhase){hudPhase.textContent=prompt;}
if(hudGesture){hudGesture.textContent=gesture.textContent+(typeof live.confidence==='number'?'（'+Math.round(live.confidence*100)+'%）':'');}
stable.textContent=typeof live.stable_ms==='number'?live.stable_ms+' 毫秒':'--';
validity.textContent=liveStale?'已过期':liveUnavailable?'识别暂不可用':liveError==='NO_HAND'||liveError==='HAND_NOT_FOUND'?'未检测到手':typeof live.valid==='boolean'?(live.valid?'有效':'无效'):'--';
if(!liveStale&&live.valid===true&&stKey==='IMITATING'&&x.motion_progress)validity.textContent='连续动作观察中';
var courseError=String(x.session_error_code||'').toLowerCase();
errorCode.textContent=mapReason(courseError&&courseError!=='ok'?x.session_error_code:(x.error_code||x.reason),'无');
var shape=x.shape_debug;
if(fingerDebug)fingerDebug.textContent=shape&&Array.isArray(shape.finger_extension)?shape.finger_extension.join(' / '):'未上报';
if(thumbDebug)thumbDebug.textContent=shape&&typeof shape.thumb_extension==='number'?String(shape.thumb_extension):'未上报';
if(candidateDebug)candidateDebug.textContent=shape&&shape.top_candidate?mapGesture(shape.top_candidate):'未上报';
var reqSt=x.request_state?mapRequest(x.request_state):'';
var reqRs=(x.request_reason||x.error_code||x.reason);
if(reqSt&&reqRs&&String(reqRs).toLowerCase()!=='ok'&&String(reqRs).toLowerCase()!==String(x.request_state).toLowerCase()){
message.textContent=reqSt+'（'+mapReason(reqRs)+'）';
}else if(reqSt){
message.textContent=reqSt;
}else if(reqRs){
message.textContent=mapReason(reqRs,'就绪');
}else{
message.textContent='就绪';
}
sb.disabled=posting||x.can_start!==true;
cb.disabled=posting||x.can_cancel!==true;
var courseBanner=renderCourseGuide(x,stKey);
if(courseBanner){stepAlert.textContent=courseBanner;if(hudPhase)hudPhase.textContent=courseBanner;}

var errLower=String(x.error_code||x.reason||'').toLowerCase();
var titanText='未上报';
var titanClass='unknown';
if(errLower.indexOf('link_offline')!==-1||errLower.indexOf('titan_link_offline')!==-1){
titanText='断开';
titanClass='err';
}else if(typeof x.link_online==='boolean'){
titanText=x.link_online?'在线':'断开';
titanClass=x.link_online?'ok':'err';
}else{
titanText='未上报';
titanClass='unknown';
}
if(healthTitan){
healthTitan.textContent=titanText;
healthTitan.className='health-val '+titanClass;
}

var isMechanicalRunning=false;
var isMechanicalCompleted=false;
var motionText='未上报';
var motionClass='unknown';
var m=x.mechanical_motion;
if(m&&typeof m==='object'&&typeof m.state==='number'){
if(m.state===2){
motionText='运行中';
motionClass='ok';
isMechanicalRunning=true;
}else if(m.state===1){
motionText='排队中';
motionClass='warn';
}else if(m.state===5){
if(m.result===1){
motionText='动作完成';
motionClass='ok';
isMechanicalCompleted=true;
}else{
motionText='已结束';
motionClass='unknown';
}
}else if(m.state===6){
motionText='已取消';
motionClass='warn';
}else if(m.state===7||m.result===2){
motionText='动作故障';
motionClass='err';
}else if(m.state===0){
if(x.link_online===true){
motionText='就绪';
motionClass='ok';
}else if(titanText==='断开'){
motionText='不可用（Titan 断开）';
motionClass='err';
}else{
motionText='等待 Titan 状态';
motionClass='warn';
}
}else{
motionText='状态('+m.state+')';
motionClass='unknown';
}
}else{
if(titanText==='断开'){
motionText='不可用（Titan 断开）';
motionClass='err';
}else{
motionText='未上报';
motionClass='unknown';
}
}
if(healthMotion){
healthMotion.textContent=motionText;
healthMotion.className='health-val '+motionClass;
}
if(motionVal){
motionVal.textContent=motionText;
}

var ai=x.aitrust;
var nowMono=getMonoTime();
if(ai&&typeof ai==='object'){
var curGen=(typeof ai.generation==='number')?ai.generation:(typeof ai.seq==='number'?ai.seq:null);
if(curGen!==null&&curGen!==lastAiTrustGen){
lastAiTrustGen=curGen;
lastAiTrustMonoTime=nowMono;
}
}
var aiExpired=false;
if(ai&&typeof ai==='object'){
if(ai.expired===true||ai.state==='expired'){
aiExpired=true;
}else if(lastAiTrustMonoTime!==null&&(nowMono-lastAiTrustMonoTime>1500)){
aiExpired=true;
}
}

var isTitanOnline=(x.link_online===true&&titanText==='在线');
var isReady=(ai&&typeof ai==='object'&&(ai.ready===true||ai.ready===1));
var aiText='未上报';
var aiClass='unknown';

if(errLower.indexOf('link_offline')!==-1||errLower.indexOf('titan_link_offline')!==-1||x.link_online===false||titanText==='断开'){
aiText='链路离线';
aiClass='err';
}else if(!ai||typeof ai!=='object'||ai.state==='not_reported'||lastAiTrustMonoTime===null){
aiText='未上报';
aiClass='unknown';
}else if(aiExpired){
aiText='已过期';
aiClass='warn';
}else if(!isTitanOnline){
aiText=(titanText==='未上报')?'未上报':'链路离线';
aiClass=(titanText==='未上报')?'unknown':'err';
}else if(!isReady){
aiText='未就绪';
aiClass='warn';
}else if(ai.class_id===0){
aiText='可信';
aiClass='ok';
}else if(ai.class_id===1){
aiText='存疑';
aiClass='warn';
}else if(ai.class_id===2){
aiText='异常';
aiClass='err';
}else{
aiText='未就绪';
aiClass='warn';
}

if(healthAiTrust){
healthAiTrust.textContent=aiText;
healthAiTrust.className='health-val '+aiClass;
}
if(aitrustVal){
aitrustVal.textContent=aiText;
}

var visionText='未上报';
var visionClass='unknown';
if(liveStale){
visionText='识别已过期';visionClass='warn';
}else if(liveUnavailable){
visionText='识别暂不可用';visionClass='warn';
}else if(liveError==='NO_HAND'||liveError==='HAND_NOT_FOUND'){
visionText='未检测到手';visionClass='warn';
}else if(live.valid===true){
visionText='已锁定手型';
visionClass='ok';
}else if(live.gesture_id&&live.gesture_id!=='--'&&String(live.gesture_id).toLowerCase()!=='none'&&String(live.gesture_id).toLowerCase()!=='unknown'){
visionText='检测到手势';
visionClass='ok';
}else if(errLower==='hand_not_found'||errLower==='no_hand'){
visionText='未检测到手';
visionClass='warn';
}else if(liveError==='LOW_CONFIDENCE'){
visionText='置信度不足';
visionClass='warn';
}else if(x.state&&x.state!=='disabled'){
visionText='检测中';
visionClass='ok';
}
if(healthVision){
healthVision.textContent=visionText;
healthVision.className='health-val '+visionClass;
}

updateProcessBar(stKey,Boolean(x.lesson_id),isMechanicalRunning,isMechanicalCompleted,Boolean(x.motion_progress&&x.motion_progress.complete===true));

var cur=x.lesson_id||'';
var cards=['basic_open_palm','basic_fist','basic_v_sign','basic_point','basic_thumbs_up','basic_l_shape','basic_ok_pinch','word_hello','word_thanks','signal_help','word_no','word_attention','word_like'];
for(var i=0;i<cards.length;i++){
var el=document.getElementById('card_'+cards[i]);
if(el){el.className=(cards[i]===cur)?'ref-card active':'ref-card';}
}
if(cur&&(!levelRun||levelRun.stopped||cur===levelRun.lessons[levelRun.index])){
updateDetail(cur);
}
}

function r(){
if(inflight)return;
inflight=true;
get('/api/v1/sign/status')
.catch(function(){return{state:'disabled',reason:'sign_disabled'};})
.then(function(signData){
showSign(signData);
return get('/api/v1/train/status');
})
.then(function(x){
var ok=x.can_submit===true&&x.state!=='pending'&&x.state!=='submitted';
b.disabled=posting||!ok;
s.textContent=ok?'检测到水瓶，可手动开始':'等待稳定水瓶与 Titan 就绪：'+text(mapReason(x.availability_reason||x.reason||x.state),'不可用')
})
.catch(function(){b.disabled=true;s.textContent='设备状态不可用'})
.then(function(){inflight=false})
}

Array.prototype.forEach.call(document.querySelectorAll('[data-tab]'),function(btn){
btn.onclick=function(){
var tab=btn.getAttribute('data-tab');
Array.prototype.forEach.call(document.querySelectorAll('[data-tab]'),function(t){
t.className=(t===btn)?'tab-btn active':'tab-btn';
});
Array.prototype.forEach.call(document.querySelectorAll('.course-grid .ref-card'),function(c){
if(tab==='all'||c.getAttribute('data-cat')===tab){
c.style.display='flex';
}else{
c.style.display='none';
}
});
};
});

Array.prototype.forEach.call(document.querySelectorAll('[data-lesson]'),function(x){
x.onclick=function(){
if(posting)return;
var lid=x.getAttribute('data-lesson');
invalidateAdviceSelection();
if(levelRun&&!levelRun.stopped&&lid!==levelRun.lessons[levelRun.index]&&
currentSignState!=='DEMONSTRATING'&&currentSignState!=='IMITATING'){
levelRun.stopped=true;
renderLevelReport();
if(levelProgress)levelProgress.textContent='已退出分级训练；已有记录可下载。';
if(levelNext)levelNext.disabled=true;
renderCourseGuide(null,'');
}
updateDetail(lid);
message.textContent='正在选择课程…';
post('/api/v1/sign/select',{lesson_id:lid});
};
});
function beginCourse(config,key,isRemedial){
if(posting||currentSignState==='DEMONSTRATING'||currentSignState==='IMITATING')return;
if(!config)return;
levelRun={name:config.name,lessons:config.lessons.slice(),index:0,rows:[],
key:key,isRemedial:isRemedial===true,
archiveId:Date.now().toString(36)+'_'+Math.random().toString(36).slice(2,10),archiveTime:Date.now(),
startedAt:new Date().toLocaleString(),seenActive:false,recorded:false,itemStart:null,stopped:false,
samples:{observations:0,low_confidence:0,no_hand:0,wrong_gesture:0,vision_stale:0,max_stable_ms:0}};
clearAiAdvice();
if(levelAiAdvice)levelAiAdvice.disabled=true;
if(levelAiRecorded)levelAiRecorded.textContent='0 / '+config.lessons.length+' 项';
if(levelAiCompleted)levelAiCompleted.textContent='0 项';
if(levelAiFocus)levelAiFocus.textContent='等待训练';
var overview=document.getElementById('reportOverview'),practice=document.getElementById('reportNextPractice');
if(overview)overview.textContent='尚无课程结果；这是进行中的记录。';
if(practice)practice.textContent='先完成一项练习，再依据记录选择复练重点。';
if(levelAiResult)levelAiResult.textContent='本次不足\\n完成至少一项课程后，这里显示规则归纳的不足。\\n证据局限\\n新动态课程评估二维动作顺序原型；没有步骤记录的旧结果不是完整连续动作通过。\\n下次练习建议\\n点击“生成 AI 下次训练建议”后，模型参考会出现在这里。模型文字不改变课程判定。';
setAiBadge('待生成','');
if(levelAiStatus)levelAiStatus.textContent='完成至少一项后，可在电脑上手动生成 AI 建议。';
if(levelReport)levelReport.hidden=true;
if(levelNext)levelNext.disabled=true;
if(levelDownload)levelDownload.disabled=true;
if(levelProgress)levelProgress.textContent=config.name+' 1/'+config.lessons.length+'：'+mapLesson(config.lessons[0])+'。选择后仍需人工确认开始。';
updateDetail(config.lessons[0]);
renderCourseGuide(null,'');
post('/api/v1/sign/select',{lesson_id:config.lessons[0]});
}
Array.prototype.forEach.call(document.querySelectorAll('[data-level]'),function(btn){
btn.onclick=function(){
var key=btn.getAttribute('data-level');beginCourse(LEVELS[key],key,false);
};
});
if(historyToggle)historyToggle.onclick=function(){
historyEnabled=!historyEnabled;
historyToggle.textContent=historyEnabled?'停止本机保存':'开启本机记录';
if(historyEnabled)persistCourseHistory();
else{try{localStorage.removeItem(historyKey);
if(historyStatus)historyStatus.textContent='已停止保存并移除持久记录；本页内存记录仍可查看，刷新后丢失。';
}catch(e){if(historyStatus)historyStatus.textContent='已停止后续保存，但浏览器拒绝移除旧记录；请在浏览器设置中清理此站点数据。';}}
};
if(historyClear)historyClear.onclick=function(){
courseHistory=[];historyEnabled=false;
try{localStorage.removeItem(historyKey);
if(historyStatus)historyStatus.textContent='本机记录已清除，保存已关闭。';
}catch(e){if(historyStatus)historyStatus.textContent='浏览器拒绝清除持久记录；已清空本页内存，请在浏览器设置中清理此站点数据。';}
if(historyToggle)historyToggle.textContent='开启本机记录';renderCourseHistory();
};
if(levelRemedial)levelRemedial.onclick=function(){
var s=latestCourse(),plan=remedialLessons(s);if(!plan.length)return;
beginCourse({name:LEVELS[s.level].name+'针对性复练',lessons:plan},s.level,true);
};
if(levelNext)levelNext.onclick=function(){
if(!levelRun||levelRun.stopped||!levelRun.recorded||posting||
levelRun.index+1>=levelRun.lessons.length)return;
invalidateAdviceSelection();
levelRun.index++;
levelRun.seenActive=false;
levelRun.recorded=false;
levelRun.itemStart=null;
levelRun.samples={observations:0,low_confidence:0,no_hand:0,wrong_gesture:0,vision_stale:0,max_stable_ms:0};
levelNext.disabled=true;
var lid=levelRun.lessons[levelRun.index];
updateDetail(lid);
renderCourseGuide(null,'');
post('/api/v1/sign/select',{lesson_id:lid});
};
if(levelReselect)levelReselect.onclick=function(){
if(!levelRun||levelRun.stopped||levelRun.recorded||posting||currentSignState==='DEMONSTRATING'||currentSignState==='IMITATING')return;
invalidateAdviceSelection();
post('/api/v1/sign/select',{lesson_id:levelRun.lessons[levelRun.index]});
};
if(levelReportJump)levelReportJump.onclick=function(){
var analysis=document.getElementById('analysis');
if(analysis&&typeof analysis.scrollIntoView==='function')analysis.scrollIntoView({behavior:'smooth',block:'start'});
};
if(levelDownload)levelDownload.onclick=function(){
if(!levelRun||!levelRun.rows.length||!levelReport)return;
renderLevelReport();
var blob=new Blob([levelReport.textContent],{type:'text/plain;charset=utf-8'});
var url=URL.createObjectURL(blob),link=document.createElement('a');
link.href=url;link.download='OpenSignHand_'+levelRun.name+'_训练报告.txt';
document.body.appendChild(link);link.click();document.body.removeChild(link);
setTimeout(function(){URL.revokeObjectURL(url);},1000);
};
if(levelAiAdvice)levelAiAdvice.onclick=function(){
if(!levelRun||!levelRun.rows.length||aiAdviceBusy)return;
var targetRun=levelRun,rowCount=targetRun.rows.length,requestEpoch=aiAdviceEpoch;
var knownReasons=['OK','NONE','TIMEOUT','CANCELLED','FAULT','MANUAL_REVIEW','EXTERNAL_FAULT','NO_HAND','HAND_NOT_FOUND','INVALID_LANDMARKS','LOW_CONFIDENCE','WRONG_GESTURE','TARGET_MISMATCH','LINK_OFFLINE','VISION_STALE','INVALID_RESULT','UNKNOWN_GESTURE'];
var rows=targetRun.rows.map(function(row){
var reason=String(row.error_code||'NONE').toUpperCase();
var aiRow={lesson_id:row.lesson_id,state:row.state,duration_s:row.duration_s,
confidence_pct:typeof row.confidence==='string'&&/^\\d{1,3}%$/.test(row.confidence)?parseInt(row.confidence,10):null,
error_code:knownReasons.indexOf(reason)>=0?reason:'NONE',samples:row.samples};
var aiMotion=cleanMotionProgress(row.motion_progress);if(aiMotion)aiRow.motion_progress={completed_steps:aiMotion.completed_steps,total_steps:aiMotion.total_steps,complete:aiMotion.complete};
if(validCompletionHold(row))aiRow.completion_stable_ms=row.completion_stable_ms;
return aiRow;
});
aiAdviceBusy=true;levelAiAdvice.disabled=true;
setAiBadge('分析中','loading');
if(levelAiStatus)levelAiStatus.textContent='正在生成建议；原有报告仍可使用…';
var controller=new AbortController(),timer=setTimeout(function(){controller.abort();},15000);
var aiSummary={level:targetRun.key,rows:rows};
if(targetRun.isRemedial)aiSummary.plan=targetRun.lessons.slice();
fetch('http://127.0.0.1:8765/api/v1/ai/course-advice',{
method:'POST',headers:{'Content-Type':'application/json'},
body:JSON.stringify(aiSummary),signal:controller.signal
}).then(function(response){
return response.json().then(function(payload){
if(!response.ok){var err=new Error('HTTP '+response.status);err.code=payload&&payload.error;throw err;}
return payload;
},function(){if(!response.ok)throw new Error('HTTP '+response.status);throw new Error('bad json');});
}).then(function(result){
if(requestEpoch!==aiAdviceEpoch)return;
if(levelRun!==targetRun||targetRun.rows.length!==rowCount){
if(levelRun===targetRun){clearAiAdvice();setAiBadge('待生成','');if(levelAiStatus)levelAiStatus.textContent='训练记录已变化，请重新生成 AI 建议。';}
return;
}
var accepted=acceptAdviceContract(result);
if(!accepted)throw new Error('invalid contract');
aiAdviceText=accepted.advice;aiAdviceSource=accepted.source;aiAdviceReason=accepted.reason;aiNotice='';
setAiBadge(accepted.source==='model'?'模型建议':'本地建议',accepted.source==='model'?'ready':'local');
renderLevelReport();
if(levelAiStatus)levelAiStatus.textContent=accepted.source==='model'?'模型建议已写入本次报告，下载时一并保存。仅供参考，不改变课程判定，不触发机械动作。':'本地规则建议已写入本次报告，未采用模型结果。下载时一并保存。不改变课程判定，不触发机械动作。';
}).catch(function(err){
if(requestEpoch!==aiAdviceEpoch||levelRun!==targetRun||targetRun.rows.length!==rowCount)return;
clearAiAdvice();
aiNotice='分析暂不可用。下方规则报告和下载功能仍可使用。';
renderLevelReport();
setAiBadge('暂不可用','error');
var code=err&&err.code,hint='分析暂不可用。原有训练报告不受影响。';
if(code==='api_key_rejected')hint='分析暂不可用。密钥被拒绝；原有训练与规则报告仍可使用。';
else if(code==='provider_timeout')hint='分析暂不可用。模型响应超时；原有训练与规则报告仍可使用。';
else if(code==='provider_unavailable')hint='分析暂不可用。模型服务不可用；原有训练与规则报告仍可使用。';
if(levelAiStatus)levelAiStatus.textContent=hint;
}).then(function(){clearTimeout(timer);aiAdviceBusy=false;if(levelAiAdvice)levelAiAdvice.disabled=!levelRun||!levelRun.rows.length;});
};
sb.onclick=function(){if(!posting&&!sb.disabled&&!sb.hidden)post('/api/v1/sign/start',null)};
cb.onclick=function(){if(!posting)post('/api/v1/sign/cancel',null)};
if(manualReviewConsent)manualReviewConsent.onchange=function(){manualReviewButton.disabled=posting||!manualReviewRun||manualReviewConsent.checked!==true;};
if(manualReviewButton)manualReviewButton.onclick=function(){
if(posting||manualReviewButton.disabled||manualReviewConsent.checked!==true||!manualReviewRun)return;
var body={lesson_id:manualReviewRun.lesson_id,session_token:manualReviewRun.session_token,manual_confirm:true};
manualReviewConsent.checked=false;manualReviewButton.disabled=true;
manualReviewNotice.textContent='正在记录操作者复核；不会触发机械动作，不计自动通过。';
post('/api/v1/sign/review',body);
};
b.onclick=function(){b.disabled=true;fetch('/api/v1/train',{method:'POST',body:''}).then(function(r){return r.json()}).then(function(x){s.textContent=x.state+(x.reason?': '+x.reason:'')}).catch(function(){s.textContent='请求被拒绝'}).then(r)};
function aitrustWatchdog(){
var nowMono=getMonoTime();
if(lastLiveObservationMono!==null&&nowMono-lastLiveObservationMono>=1500){
sequenceUnavailable('没有新的实时读数，已清除旧图像条件；教学说明仍可查看。');
gesture.textContent='识别已过期';confidence.textContent='--';stable.textContent='--';validity.textContent='已过期';
if(hudGesture)hudGesture.textContent='识别已过期';
if(healthVision){healthVision.textContent='识别已过期';healthVision.className='health-val warn';}
}
if(lastSignMono!==null&&nowMono-lastSignMono>=1500){
renderManualReview({});
sequenceUnavailable('设备状态已过期；不以旧图像条件认定动作。');
if(fingerCoach)fingerCoach.textContent='';
if(coachAdvice)coachAdvice.textContent='网页设备状态已过期，暂停手型建议；请检查连接。';
}
if(lastAiTrustMonoTime!==null&&(nowMono-lastAiTrustMonoTime>1500)){
if(healthAiTrust&&healthAiTrust.textContent!=='链路离线'&&healthAiTrust.textContent!=='未上报'&&healthAiTrust.textContent!=='已过期'){
healthAiTrust.textContent='已过期';
healthAiTrust.className='health-val warn';
}
if(aitrustVal&&aitrustVal.textContent!=='链路离线'&&aitrustVal.textContent!=='未上报'&&aitrustVal.textContent!=='已过期'){
aitrustVal.textContent='已过期';
}
}
}
setInterval(aitrustWatchdog,200);
setInterval(r,500);
loadCourseHistory();renderCourseHistory();
r();
}())
</script></body></html>""".encode("utf-8")


def _safe_control_text(value, fallback):
    if not isinstance(value, str) or not value or len(value) > 64:
        return fallback
    for char in value:
        if not (
            ("a" <= char <= "z") or ("A" <= char <= "Z")
            or ("0" <= char <= "9") or char == "_"
        ):
            return fallback
    return value


def _control_json(
    request_id, state, reason=None, *, include_availability=False,
    can_submit=False, availability_reason=None,
):
    request_id = request_id if type(request_id) is int and request_id >= 0 else 0
    state = _safe_control_text(state, "rejected")
    reason = "null" if reason is None else '"{}"'.format(
        _safe_control_text(reason, "unknown")
    )
    if not include_availability:
        return ('{"request_id":%d,"state":"%s","reason":%s}' % (
            request_id, state, reason
        )).encode("ascii")
    availability = "true" if can_submit is True else "false"
    availability_reason = "null" if availability_reason is None else '"{}"'.format(
        _safe_control_text(availability_reason, "availability_unknown")
    )
    return ('{"request_id":%d,"state":"%s","reason":%s,'
            '"can_submit":%s,"availability_reason":%s}' % (
                request_id, state, reason, availability, availability_reason
            )).encode("ascii")


class LatestFrameStore:
    """One-slot JPEG buffer. Publishing replaces, never queues, a frame."""

    def __init__(self, max_frame_bytes=512 * 1024):
        if type(max_frame_bytes) is not int or max_frame_bytes < 1024:
            raise ValueError("max_frame_bytes must be an integer >= 1024")
        self.max_frame_bytes = max_frame_bytes
        self._jpeg = None
        self.sequence = 0
        self.published_ms = None
        self.published = 0
        self.dropped = 0
        self.rejected = 0

    def publish(self, jpeg, now_ms):
        if not isinstance(jpeg, (bytes, bytearray, memoryview)):
            self.rejected += 1
            return False
        jpeg = bytes(jpeg)
        if not jpeg or len(jpeg) > self.max_frame_bytes:
            self.rejected += 1
            return False
        if self._jpeg is not None:
            self.dropped += 1
        self._jpeg = jpeg
        self.sequence += 1
        self.published_ms = int(now_ms)
        self.published += 1
        return True

    def snapshot(self):
        return self.sequence, self._jpeg, self.published_ms


class LatestImageStore:
    """One-slot JPEG *Image* store for the official Maix JpegStreamer API.

    The documented ``JpegStreamer.write`` accepts a JPEG ``maix.image.Image``
    rather than byte data.  Keeping this store separate from ``LatestFrameStore``
    prevents the fallback HTTP wire representation from leaking into that API.
    No Maix type is imported here; an opaque non-bytes object is retained.
    """

    def __init__(self):
        self._image = None
        self.sequence = 0
        self.published_ms = None
        self.published = 0
        self.dropped = 0
        self.rejected = 0

    def publish(self, jpeg_image, now_ms):
        if jpeg_image is None or isinstance(jpeg_image, (bytes, bytearray, memoryview)):
            self.rejected += 1
            return False
        if self._image is not None:
            self.dropped += 1
        self._image = jpeg_image
        self.sequence += 1
        self.published_ms = int(now_ms)
        self.published += 1
        return True

    def snapshot(self):
        return self.sequence, self._image, self.published_ms


class JpegEncoderAdapter:
    """Explicit adapter around a deployment-verified frame-to-JPEG callback.

    MaixPy image encoding APIs vary by firmware.  To avoid assuming one, the
    caller supplies a verified callable (for example, a small on-device
    wrapper around the API available in that firmware).  Failure is contained
    and recorded, never raised into the vision/UART loop by default.
    """

    def __init__(self, encode_callable=None):
        self.encode_callable = encode_callable
        self.successes = 0
        self.failures = 0
        self.last_fault = None

    @property
    def available(self):
        return callable(self.encode_callable)

    def encode(self, frame):
        if not self.available:
            self.last_fault = "jpeg_encoder_unavailable"
            return None
        try:
            encoded = self.encode_callable(frame)
            if not isinstance(encoded, (bytes, bytearray, memoryview)):
                raise TypeError("encoder did not return JPEG bytes")
            self.successes += 1
            self.last_fault = None
            return bytes(encoded)
        except Exception as exc:
            self.failures += 1
            self.last_fault = "jpeg_encode_failed:{}".format(type(exc).__name__)
            return None


class MaixJpegStreamerAdapter:
    """Lazy adapter for the official ``maix.http.JpegStreamer`` path.

    It is intentionally inactive until ``start`` is called.  No runtime API is
    guessed: the adapter checks the documented objects at that point, and uses
    only ``frame.to_jpeg()`` and ``stream.write(jpeg)``.  Since firmware-level
    backpressure behaviour must be measured on a real device, callers keep
    ``flush_latest`` outside the vision/UART critical path until that test has
    passed.  The bounded store still ensures this layer never queues frames.
    """

    def __init__(self, images=None, maix_http=None):
        self.images = images or LatestImageStore()
        self._maix_http = maix_http
        self._runtime_http = None
        self.stream = None
        self.started = False
        self.attempted_sequence = 0
        self.written_sequence = 0
        self.writes = 0
        self.failures = 0
        self.last_fault = None

    @staticmethod
    def _err_success(result, module):
        """Accept test-double ``None`` and Maix ``ERR_NONE``/zero only."""
        if result is None or result == 0:
            return True
        for holder in (
            module,
            getattr(module, "Err", None),
            getattr(module, "err", None),
            type(result),
            result,
        ):
            if holder is not None and result == getattr(holder, "ERR_NONE", object()):
                return True
        return False

    @staticmethod
    def _err_text(result):
        try:
            return str(result)
        except Exception:
            return type(result).__name__

    def start(self):
        if self.started:
            return True
        module = self._maix_http
        if module is None:
            try:
                from maix import http as module
            except Exception as exc:
                self.last_fault = "maix_http_unavailable:{}".format(type(exc).__name__)
                return False
        streamer_type = getattr(module, "JpegStreamer", None)
        if not callable(streamer_type):
            self.last_fault = "jpeg_streamer_unavailable"
            return False
        try:
            stream = streamer_type()
            result = stream.start()
        except Exception as exc:
            self.last_fault = "jpeg_streamer_start_failed:{}".format(type(exc).__name__)
            return False
        if not self._err_success(result, module):
            self.last_fault = "jpeg_streamer_start_failed:err={}".format(
                self._err_text(result)
            )
            self._safe_stop(stream, module, preserve_fault=True)
            return False
        self._runtime_http = module
        self.stream = stream
        self.started = True
        self.last_fault = None
        return True

    def _safe_stop(self, stream, module, preserve_fault=False):
        """Stop a streamer without allowing cleanup failures to escape."""
        stop = getattr(stream, "stop", None)
        if not callable(stop):
            if not preserve_fault:
                self.last_fault = "jpeg_streamer_stop_unavailable"
            return False
        try:
            result = stop()
        except Exception as exc:
            if not preserve_fault:
                self.last_fault = "jpeg_streamer_stop_failed:{}".format(
                    type(exc).__name__
                )
            return False
        if not self._err_success(result, module):
            if not preserve_fault:
                self.last_fault = "jpeg_streamer_stop_failed:err={}".format(
                    self._err_text(result)
                )
            return False
        return True

    def close(self):
        """Best-effort streamer shutdown; always reset local lifecycle state."""
        stream = self.stream
        module = self._runtime_http or self._maix_http
        self.stream = None
        self._runtime_http = None
        self.started = False
        self.attempted_sequence = 0
        self.written_sequence = 0
        if stream is None:
            return True
        stopped = self._safe_stop(stream, module)
        if stopped:
            self.last_fault = None
        return stopped

    def stop(self):
        """Alias for callers whose lifecycle API uses ``stop`` instead of close."""
        return self.close()

    def offer_frame(self, frame, now_ms):
        """Encode one annotated frame; failure is safely recorded and dropped."""
        try:
            jpeg = frame.to_jpeg()
        except Exception as exc:
            self.failures += 1
            self.last_fault = "frame_to_jpeg_failed:{}".format(type(exc).__name__)
            return False
        return self.images.publish(jpeg, now_ms)

    def flush_latest(self):
        """Write at most one newest JPEG; never drains a frame queue."""
        if not self.started or self.stream is None:
            return False
        sequence, jpeg_image, _published_ms = self.images.snapshot()
        if jpeg_image is None or sequence == self.attempted_sequence:
            return False
        # Latest-only policy: a sequence is attempted once.  A failed write is
        # not counted as written, but is never retried; a newer frame replaces
        # it on the next publish instead of producing duplicate network work.
        self.attempted_sequence = sequence
        try:
            result = self.stream.write(jpeg_image)
        except Exception as exc:
            self.failures += 1
            self.last_fault = "jpeg_streamer_write_failed:{}".format(type(exc).__name__)
            return False
        if not self._err_success(result, self._runtime_http or self._maix_http):
            self.failures += 1
            self.last_fault = "jpeg_streamer_write_failed:err={}".format(
                self._err_text(result)
            )
            return False
        self.written_sequence = sequence
        self.writes += 1
        self.last_fault = None
        return True


def detect_socket_capabilities(socket_module=None):
    """Return only detected capabilities; this function performs no I/O."""
    module = _system_socket if socket_module is None else socket_module
    return {
        "socket_module": module is not None,
        "socket_factory": callable(getattr(module, "socket", None)) if module else False,
        "af_inet": hasattr(module, "AF_INET") if module else False,
        "sock_stream": hasattr(module, "SOCK_STREAM") if module else False,
    }


def _would_block(exc):
    code = getattr(exc, "errno", None)
    return code in (11, 35, 10035) or exc.__class__.__name__ in ("BlockingIOError", "EAGAIN")


class _Client:
    def __init__(self, connection):
        self.connection = connection
        self.request = bytearray()
        self.mode = "request"
        self.send_buffer = b""
        self.sent_sequence = 0
        self.would_block_count = 0


class PreviewServer:
    """Cooperatively-polled non-blocking MJPEG and JSON HTTP sidecar."""

    def __init__(
        self,
        frames=None,
        telemetry_provider=None,
        train_request_handler=None,
        train_status_provider=None,
        sign_select_handler=None,
        sign_start_handler=None,
        sign_cancel_handler=None,
        sign_status_provider=None,
        socket_module=None,
        max_clients=3,
        max_consecutive_would_block=3,
        sign_review_handler=None,
    ):
        if type(max_clients) is not int or max_clients < 1:
            raise ValueError("max_clients must be a positive integer")
        if (
            type(max_consecutive_would_block) is not int
            or max_consecutive_would_block < 1
        ):
            raise ValueError("max_consecutive_would_block must be a positive integer")
        self.frames = frames or LatestFrameStore()
        self.telemetry_provider = telemetry_provider
        self.train_request_handler = train_request_handler
        self.train_status_provider = train_status_provider
        # Sign handlers are intentionally transport callbacks only.  The
        # caller owns the bounded command queue; these callbacks must never
        # receive serial/UART objects or a servo angle payload.
        self.sign_select_handler = sign_select_handler
        self.sign_start_handler = sign_start_handler
        self.sign_cancel_handler = sign_cancel_handler
        self.sign_review_handler = sign_review_handler
        self.sign_status_provider = sign_status_provider
        self.socket_module = _system_socket if socket_module is None else socket_module
        self.max_clients = max_clients
        self.max_consecutive_would_block = max_consecutive_would_block
        self.listener = None
        self.clients = []
        self.started = False
        self.accepted = 0
        self.dropped_clients = 0
        self.io_faults = 0
        self.last_fault = None

    def start(self, host="0.0.0.0", port=8080, backlog=2):
        """Explicitly bind a non-blocking listener. Returns False if unavailable."""
        if self.started:
            return True
        caps = detect_socket_capabilities(self.socket_module)
        if not all(caps.values()):
            self.last_fault = "socket_capability_unavailable"
            return False
        listener = None
        try:
            listener = self.socket_module.socket(
                self.socket_module.AF_INET, self.socket_module.SOCK_STREAM
            )
            reuse = getattr(self.socket_module, "SO_REUSEADDR", None)
            set_opt = getattr(listener, "setsockopt", None)
            if reuse is not None and callable(set_opt):
                set_opt(getattr(self.socket_module, "SOL_SOCKET", 1), reuse, 1)
            listener.bind((host, int(port)))
            listener.listen(int(backlog))
            listener.setblocking(False)
        except Exception as exc:
            self.last_fault = "socket_start_failed:{}".format(type(exc).__name__)
            try:
                listener.close()
            except Exception:
                pass
            return False
        self.listener = listener
        self.started = True
        self.last_fault = None
        return True

    def close(self):
        for client in list(self.clients):
            self._drop(client)
        if self.listener is not None:
            try:
                self.listener.close()
            except Exception:
                pass
        self.listener = None
        self.started = False

    def publish_jpeg(self, jpeg, now_ms):
        """Non-I/O producer hook; rejection is local and non-fatal."""
        return self.frames.publish(jpeg, now_ms)

    def publish_frame(self, frame, encoder, now_ms):
        """Optional explicit encoder hook; no Maix API is assumed here."""
        jpeg = encoder.encode(frame)
        return False if jpeg is None else self.publish_jpeg(jpeg, now_ms)

    def poll(self, max_accepts=1, max_client_writes=4):
        """Perform a bounded amount of non-blocking socket work then return."""
        if not self.started or self.listener is None:
            return 0
        work = 0
        for _ in range(max(0, int(max_accepts))):
            try:
                connection, _address = self.listener.accept()
                connection.setblocking(False)
            except Exception as exc:
                if not _would_block(exc):
                    self.io_faults += 1
                    self.last_fault = "accept_failed:{}".format(type(exc).__name__)
                break
            if len(self.clients) >= self.max_clients:
                try:
                    connection.close()
                except Exception:
                    pass
                self.dropped_clients += 1
                continue
            self.clients.append(_Client(connection))
            self.accepted += 1
            work += 1
        for client in list(self.clients):
            if client.mode == "request":
                self._read_request(client)
        writes = 0
        for client in list(self.clients):
            if writes >= max(0, int(max_client_writes)):
                break
            if self._write_once(client):
                writes += 1
                work += 1
        return work

    def _read_request(self, client):
        try:
            data = client.connection.recv(512)
        except Exception as exc:
            if not _would_block(exc):
                self._drop(client)
            return
        if not data:
            self._drop(client)
            return
        client.request.extend(data)
        if len(client.request) > MAX_REQUEST_BYTES:
            self._drop(client)
            return
        if b"\r\n\r\n" not in client.request and b"\n\n" not in client.request:
            return
        raw_request = bytes(client.request)
        request_line = raw_request.splitlines()[0].split()
        if len(request_line) < 2:
            self._queue_response(
                client,
                self._http_response(b"application/json", b'{"error":"invalid_request"}', b"400 Bad Request", cors=False),
                "close",
            )
            return
        method = request_line[0]
        path = request_line[1]
        if method == b"POST":
            request_ready = self._post_request_complete(raw_request)
            if request_ready is False:
                return
            if path == b"/api/v1/train":
                self._queue_response(client, self._train_request_response(raw_request), "close")
            elif path == b"/api/v1/sign/select":
                self._queue_response(
                    client, self._sign_request_response(raw_request, "select"), "close"
                )
            elif path == b"/api/v1/sign/start":
                self._queue_response(
                    client, self._sign_request_response(raw_request, "start"), "close"
                )
            elif path == b"/api/v1/sign/cancel":
                self._queue_response(
                    client, self._sign_request_response(raw_request, "cancel"), "close"
                )
            elif path == b"/api/v1/sign/review":
                self._queue_response(client, self._sign_request_response(raw_request, "review"), "close")
            else:
                self._queue_response(
                    client,
                    self._http_response(b"application/json", b'{"error":"not_found"}', b"404 Not Found", cors=False),
                    "close",
                )
            return
        if method != b"GET":
            self._queue_response(
                client,
                self._http_response(b"application/json", b'{"error":"method_not_allowed"}', b"405 Method Not Allowed", cors=False),
                "close",
            )
            return
        if path == b"/stream":
            self._queue_response(client, (
                b"HTTP/1.1 200 OK\r\nContent-Type: multipart/x-mixed-replace; boundary="
                + BOUNDARY.encode("ascii") + b"\r\nCache-Control: no-store\r\nAccess-Control-Allow-Origin: *\r\nConnection: close\r\n\r\n"
            ), "stream")
        elif path == b"/telemetry":
            self._queue_response(client, self._telemetry_response(), "close")
        elif path == b"/control":
            self._queue_response(
                client,
                self._http_response(b"text/html; charset=utf-8", _CONTROL_PAGE, cors=False),
                "close",
            )
        elif path == b"/api/v1/train/status":
            self._queue_response(client, self._train_status_response(), "close")
        elif path == b"/api/v1/sign/status":
            self._queue_response(client, self._sign_status_response(), "close")
        elif path in (b"/", b"/index.html"):
            body = (b"<!doctype html><meta charset=\"utf-8\"><title>OpenSignHand</title>"
                    b"<style>html,body{margin:0;padding:0;width:100%;height:100%;overflow:hidden}iframe{width:100%;height:100%;border:none}</style>"
                    b"<iframe src='/control' title='OpenSignHand manual control'></iframe>")
            self._queue_response(client, self._http_response(b"text/html; charset=utf-8", body), "close")
        else:
            self._queue_response(client, self._http_response(b"text/plain", b"not found", b"404 Not Found"), "close")

    @classmethod
    def _post_request_complete(cls, raw_request):
        """Return False while a declared POST body is still fragmented.

        Non-blocking sockets may deliver the header and JSON body in separate
        reads.  Dispatching immediately after the header delimiter would turn
        a valid same-origin command into a permanent 400 response.  Invalid or
        missing lengths remain ready so the existing request validator can
        reject them with its stable error response.
        """
        headers, body = cls._headers_and_body(raw_request)
        if headers is None or body is None:
            return True
        content_length = headers.get(b"content-length")
        try:
            declared_length = int(content_length.decode("ascii"))
        except Exception:
            return True
        if declared_length < 0 or declared_length > MAX_REQUEST_BYTES:
            return True
        return len(body) >= declared_length

    @staticmethod
    def _headers_and_body(raw_request):
        marker = b"\r\n\r\n"
        index = raw_request.find(marker)
        marker_length = len(marker)
        if index < 0:
            marker = b"\n\n"
            index = raw_request.find(marker)
            marker_length = len(marker)
        if index < 0:
            return None, None
        headers = {}
        for line in raw_request[:index].splitlines()[1:]:
            if b":" not in line:
                return None, None
            name, value = line.split(b":", 1)
            name = name.strip().lower()
            if not name or name in headers:
                return None, None
            headers[name] = value.strip()
        return headers, raw_request[index + marker_length:]

    def _train_request_response(self, raw_request):
        headers, body = self._headers_and_body(raw_request)
        if headers is None or body or headers.get(b"content-length") != b"0":
            return self._http_response(
                b"application/json", _control_json(0, "rejected", "invalid_request"),
                b"400 Bad Request", cors=False,
            )
        host = headers.get(b"host")
        origin = headers.get(b"origin")
        if not host or not origin or origin != b"http://" + host:
            return self._http_response(
                b"application/json", _control_json(0, "rejected", "origin_denied"),
                b"403 Forbidden", cors=False,
            )
        try:
            result = self.train_request_handler() if callable(self.train_request_handler) else None
        except Exception:
            result = None
        if not isinstance(result, dict):
            return self._http_response(
                b"application/json", _control_json(0, "rejected", "request_busy"),
                b"409 Conflict", cors=False,
            )
        request_id = result.get("request_id")
        if type(request_id) is not int or request_id < 1:
            return self._http_response(
                b"application/json", _control_json(0, "rejected", "request_unavailable"),
                b"503 Service Unavailable", cors=False,
            )
        return self._http_response(
            b"application/json", _control_json(request_id, "queued_for_main"),
            b"202 Accepted", cors=False,
        )

    @staticmethod
    def _json_object(raw_body):
        """Decode one bounded JSON object without accepting arbitrary input."""
        if _json is None:
            return None
        try:
            value = _json.loads(raw_body.decode("utf-8"))
        except Exception:
            return None
        return value if isinstance(value, dict) else None

    @staticmethod
    def _sign_json(request_id=0, state="rejected", reason=None, action=None):
        """Serialize a small safe sign-command response.

        This path deliberately does not echo request bodies.  In particular,
        servo angles or arbitrary client fields can never cross the HTTP
        boundary into the response or callback.
        """
        payload = {
            "request_id": request_id if type(request_id) is int and request_id >= 0 else 0,
            "state": state if isinstance(state, str) and state else "rejected",
            "reason": reason if isinstance(reason, str) and reason else None,
        }
        if isinstance(action, str) and action:
            payload["action"] = action
        if _json is not None:
            try:
                encoded = _json.dumps(payload, separators=(",", ":"))
            except TypeError:
                encoded = _json.dumps(payload)
            if isinstance(encoded, bytes):
                return encoded
            return encoded.encode("utf-8")
        # json is part of the normal MaixPy runtime.  Keep a deterministic
        # fallback for unusually constrained test/runtime images.
        reason_text = "null" if payload["reason"] is None else '"unknown"'
        action_text = "" if "action" not in payload else ',"action":"{}"'.format(payload["action"])
        return ('{"request_id":%d,"state":"%s","reason":%s%s}' % (
            payload["request_id"], payload["state"], reason_text, action_text
        )).encode("ascii")

    def _sign_request_response(self, raw_request, action):
        """Validate same-origin sign control and enqueue one safe command."""
        handler = {
            "select": self.sign_select_handler,
            "start": self.sign_start_handler,
            "cancel": self.sign_cancel_handler,
            "review": self.sign_review_handler,
        }.get(action)
        if not callable(handler):
            return self._http_response(
                b"application/json", self._sign_json(reason="sign_disabled", action=action),
                b"404 Not Found", cors=False,
            )
        headers, body = self._headers_and_body(raw_request)
        if headers is None or body is None:
            return self._http_response(
                b"application/json", self._sign_json(reason="invalid_request", action=action),
                b"400 Bad Request", cors=False,
            )
        host = headers.get(b"host")
        origin = headers.get(b"origin")
        if not host or not origin or origin != b"http://" + host:
            return self._http_response(
                b"application/json", self._sign_json(reason="origin_denied", action=action),
                b"403 Forbidden", cors=False,
            )
        content_length = headers.get(b"content-length")
        try:
            declared_length = int(content_length.decode("ascii"))
        except Exception:
            declared_length = -1
        if declared_length < 0 or declared_length != len(body) or declared_length > 256:
            return self._http_response(
                b"application/json", self._sign_json(reason="invalid_request", action=action),
                b"400 Bad Request", cors=False,
            )

        lesson_id = None
        if action in ("select", "review"):
            payload = self._json_object(body)
            # The lesson endpoint accepts exactly one field.  Reject servo
            # angles and any other future-looking controls at the boundary.
            expected_fields = {"lesson_id"} if action == "select" else {"lesson_id", "session_token", "manual_confirm"}
            if payload is None or set(payload) != expected_fields:
                return self._http_response(
                    b"application/json", self._sign_json(reason="invalid_lesson", action=action),
                    b"400 Bad Request", cors=False,
                )
            lesson_id = payload.get("lesson_id")
            if not isinstance(lesson_id, str) or not lesson_id or len(lesson_id) > 64:
                return self._http_response(
                    b"application/json", self._sign_json(reason="invalid_lesson", action=action),
                    b"400 Bad Request", cors=False,
                )
            if any(
                not (char.isalnum() or char in "_-.") for char in lesson_id
            ):
                return self._http_response(
                    b"application/json", self._sign_json(reason="invalid_lesson", action=action),
                    b"400 Bad Request", cors=False,
                )
            if action == "review" and (type(payload.get("session_token")) is not int or
                    not 1 <= payload["session_token"] <= 0x7FFFFFFF or payload.get("manual_confirm") is not True):
                return self._http_response(b"application/json", self._sign_json(reason="invalid_request", action=action), b"400 Bad Request", cors=False)
        elif body not in (b"", b"{}"):
            return self._http_response(
                b"application/json", self._sign_json(reason="invalid_request", action=action),
                b"400 Bad Request", cors=False,
            )

        try:
            result = (handler(lesson_id, payload["session_token"], True) if action == "review" else
                      handler(lesson_id) if action == "select" else handler())
        except Exception:
            result = None
        if not isinstance(result, dict):
            return self._http_response(
                b"application/json", self._sign_json(reason="request_busy", action=action),
                b"409 Conflict", cors=False,
            )
        request_id = result.get("request_id")
        if type(request_id) is not int or request_id < 1:
            return self._http_response(
                b"application/json", self._sign_json(reason="request_unavailable", action=action),
                b"503 Service Unavailable", cors=False,
            )
        return self._http_response(
            b"application/json",
            self._sign_json(request_id, "queued_for_main", action=action),
            b"202 Accepted", cors=False,
        )

    def _sign_status_response(self):
        try:
            status = self.sign_status_provider() if callable(self.sign_status_provider) else None
        except Exception:
            status = None
        if not isinstance(status, dict):
            status = {
                "request_id": 0,
                "state": "disabled",
                "reason": "sign_disabled",
            }
        # The provider owns the controller fields.  Whitelist only scalar
        # status values so a future status implementation cannot accidentally
        # expose transport objects or raw actuator data.
        request_id = status.get("request_id", 0)
        if type(request_id) is not int or request_id < 0:
            request_id = 0
        state = status.get("state", "idle")
        if not isinstance(state, str) or not state or len(state) > 64:
            state = "unavailable"
        reason = status.get("reason")
        if reason is not None and (not isinstance(reason, str) or len(reason) > 64):
            reason = "unknown"
        safe = {
            "request_id": request_id,
            "state": state,
            "reason": reason,
        }
        for key in (
            "lesson_id", "lesson_name", "gesture_id", "error_code",
            "request_state", "request_reason", "action", "demo_mode",
            "recognition_error_code", "session_error_code",
        ):
            value = status.get(key)
            if isinstance(value, str) and len(value) <= 64:
                safe[key] = value
        for key in ("confidence", "stable_ms"):
            value = status.get(key)
            if type(value) in (int, float) and value >= 0:
                safe[key] = value
        course_stable = status.get("course_stable_ms")
        if type(course_stable) is int and 0 <= course_stable <= 600000:
            safe["course_stable_ms"] = course_stable
        course_confidence = status.get("course_confidence")
        if type(course_confidence) in (int, float) and 0 <= course_confidence <= 1:
            safe["course_confidence"] = course_confidence
        course_gesture = status.get("course_gesture_id")
        if state.upper() == "COMPLETE" and isinstance(course_gesture, str) and 0 < len(course_gesture) <= 64:
            safe["course_gesture_id"] = course_gesture
        for key in ("recognition_observed_ms", "recognition_age_ms"):
            value = status.get(key)
            if type(value) is int and 0 <= value <= 8640000000000000:
                safe[key] = value
        if type(status.get("recognition_fresh")) is bool:
            safe["recognition_fresh"] = status["recognition_fresh"]
        mechanical_pose = status.get("mechanical_pose")
        if mechanical_pose is None or (
            type(mechanical_pose) is int and mechanical_pose >= 0
        ) or (isinstance(mechanical_pose, str) and len(mechanical_pose) <= 64):
            safe["mechanical_pose"] = mechanical_pose
        for key in ("valid", "can_start", "can_cancel", "can_review", "requires_confirmation"):
            value = status.get(key)
            if type(value) is bool:
                safe[key] = value
        token = status.get("session_token")
        if type(token) is int and 1 <= token <= 0x7FFFFFFF:
            safe["session_token"] = token
        shape = status.get("shape_debug")
        progress = status.get("motion_progress")
        if isinstance(progress, dict):
            completed, total = progress.get("completed_steps"), progress.get("total_steps")
            prompt = progress.get("prompt")
            if (type(completed) is int and type(total) is int and 0 <= completed <= total <= 6
                    and total > 0 and isinstance(prompt, str) and len(prompt) <= 64
                    and type(progress.get("complete")) is bool
                    and progress["complete"] == (completed == total)
                    and progress.get("scope") == "2d_sequence_prototype"):
                safe["motion_progress"] = {"completed_steps": completed, "total_steps": total,
                    "prompt": prompt, "complete": progress["complete"], "scope": "2d_sequence_prototype"}
                feedback = progress.get("feedback")
                if isinstance(feedback, str) and len(feedback) <= 64:
                    safe["motion_progress"]["feedback"] = feedback
                instruction = progress.get("instruction")
                if isinstance(instruction, str) and len(instruction) <= 160:
                    safe["motion_progress"]["instruction"] = instruction
                for key, limit in (("step_titles", 64), ("step_instructions", 160)):
                    values = progress.get(key)
                    if (isinstance(values, (list, tuple)) and len(values) == total
                            and all(isinstance(value, str) and len(value) <= limit for value in values)):
                        safe["motion_progress"][key] = list(values)
                observation = progress.get("observation_state")
                checks = progress.get("checks")
                if (observation in ("WAITING", "CHECKING", "HOLDING", "MISSING", "RESET", "COMPLETE")
                        and isinstance(checks, (list, tuple)) and len(checks) <= 4
                        and all(isinstance(item, dict) and isinstance(item.get("label"), str)
                                and len(item["label"]) <= 48 and item.get("state") in ("met", "unmet") for item in checks)):
                    safe["motion_progress"]["observation_state"] = observation
                    safe["motion_progress"]["checks"] = [{"label": item["label"], "state": item["state"]} for item in checks]
                for key in ("phase_hold_ms", "required_hold_ms"):
                    value = progress.get(key)
                    if type(value) is int and 0 <= value <= 15000:
                        safe["motion_progress"][key] = value
        if isinstance(shape, dict):
            safe_shape = {}
            fingers = shape.get("finger_extension")
            if isinstance(fingers, (list, tuple)) and len(fingers) == 4 and all(
                type(value) in (int, float) and 0 <= value <= 1 for value in fingers
            ):
                safe_shape["finger_extension"] = list(fingers)
            thumb = shape.get("thumb_extension")
            if type(thumb) in (int, float) and 0 <= thumb <= 1:
                safe_shape["thumb_extension"] = thumb
            for key in ("tip_gap", "thumb_index_gap"):
                value = shape.get(key)
                if type(value) in (int, float) and 0 <= value <= 10:
                    safe_shape[key] = value
            candidate = shape.get("top_candidate")
            if isinstance(candidate, str) and len(candidate) <= 24:
                safe_shape["top_candidate"] = candidate
            if safe_shape:
                safe["shape_debug"] = safe_shape
        motion = status.get("mechanical_motion")
        if isinstance(motion, dict):
            safe_motion = {}
            for k in ("state", "result", "completed_count", "sequence_id"):
                val = motion.get(k)
                if type(val) is int and val >= 0:
                    safe_motion[k] = val
            for k in ("last_error",):
                val = motion.get(k)
                if isinstance(val, str) and len(val) <= 64:
                    safe_motion[k] = val
            if safe_motion:
                safe["mechanical_motion"] = safe_motion
        link_online = status.get("link_online")
        if type(link_online) is bool:
            safe["link_online"] = link_online
        aitrust = status.get("aitrust")
        if isinstance(aitrust, dict):
            safe_aitrust = {}
            for k in (
                "version", "class_id", "vision_age_ms", "seq",
                "generation", "rx_time_ms",
            ):
                val = aitrust.get(k)
                if type(val) is int and val >= 0:
                    safe_aitrust[k] = val
            for k in ("ready", "expired"):
                val = aitrust.get(k)
                if type(val) is bool:
                    safe_aitrust[k] = val
            state_val = aitrust.get("state")
            if isinstance(state_val, str) and len(state_val) <= 32:
                safe_aitrust["state"] = state_val
            if safe_aitrust:
                safe["aitrust"] = safe_aitrust
        if _json is not None:
            try:
                body = _json.dumps(safe, separators=(",", ":"))
            except TypeError:
                body = _json.dumps(safe)
            if isinstance(body, str):
                body = body.encode("utf-8")
        else:
            body = self._sign_json(
                safe["request_id"], safe["state"], safe["reason"]
            )
        return self._http_response(b"application/json", body, cors=False)

    def _train_status_response(self):
        try:
            status = self.train_status_provider() if callable(self.train_status_provider) else None
        except Exception:
            status = None
        if not isinstance(status, dict):
            status = {
                "request_id": 0,
                "state": "rejected",
                "reason": "status_unavailable",
            }
        can_submit = status.get("can_submit") is True
        availability_reason = status.get("availability_reason")
        if not can_submit and availability_reason is None:
            availability_reason = "availability_unknown"
        return self._http_response(
            b"application/json",
            _control_json(
                status.get("request_id"), status.get("state"), status.get("reason"),
                include_availability=True,
                can_submit=can_submit,
                availability_reason=availability_reason,
            ),
            cors=False,
        )

    def _telemetry_response(self):
        try:
            payload = self.telemetry_provider() if callable(self.telemetry_provider) else b"{}"
            if isinstance(payload, str):
                payload = payload.encode("utf-8")
            if not isinstance(payload, bytes):
                raise TypeError("telemetry provider must return bytes or text")
            return self._http_response(b"application/json", payload)
        except Exception as exc:
            self.last_fault = "telemetry_failed:{}".format(type(exc).__name__)
            code = getattr(exc, "code", "telemetry_provider_failed")
            if (
                not isinstance(code, str)
                or not code
                or len(code) > 64
                or not all(
                    ("a" <= char <= "z")
                    or ("A" <= char <= "Z")
                    or ("0" <= char <= "9")
                    or char == "_"
                    for char in code
                )
            ):
                code = "telemetry_provider_failed"
            body = (
                b'{"error":"telemetry_unavailable","code":"'
                + code.encode("ascii") + b'"}'
            )
            return self._http_response(
                b"application/json", body, b"503 Service Unavailable"
            )

    @staticmethod
    def _http_response(content_type, body, status=b"200 OK", cors=True):
        return (b"HTTP/1.1 " + status + b"\r\nContent-Type: " + content_type
                + b"\r\nContent-Length: " + str(len(body)).encode("ascii")
                + b"\r\nCache-Control: no-store"
                + (b"\r\nAccess-Control-Allow-Origin: *" if cors else b"")
                + b"\r\nConnection: close\r\n\r\n" + body)

    @staticmethod
    def _queue_response(client, data, mode):
        client.send_buffer = data
        client.mode = mode

    def _write_once(self, client):
        if not client.send_buffer and client.mode == "stream":
            sequence, jpeg, _published_ms = self.frames.snapshot()
            if jpeg is not None and sequence != client.sent_sequence:
                client.send_buffer = (
                    b"--" + BOUNDARY.encode("ascii")
                    + b"\r\nContent-Type: image/jpeg\r\nContent-Length: "
                    + str(len(jpeg)).encode("ascii") + b"\r\n\r\n" + jpeg + b"\r\n"
                )
                client.sent_sequence = sequence
        if not client.send_buffer:
            return False
        try:
            count = client.connection.send(client.send_buffer)
        except Exception as exc:
            if _would_block(exc):
                client.would_block_count += 1
                if client.would_block_count >= self.max_consecutive_would_block:
                    self._drop(client)
            else:
                self._drop(client)
            return False
        if not count:
            self._drop(client)
            return False
        client.would_block_count = 0
        client.send_buffer = client.send_buffer[count:]
        if not client.send_buffer and client.mode == "close":
            self._drop(client)
        return True

    def _drop(self, client):
        try:
            client.connection.close()
        except Exception:
            pass
        try:
            self.clients.remove(client)
        except ValueError:
            pass
        self.dropped_clients += 1
