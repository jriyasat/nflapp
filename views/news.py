"""
News page view.
"""
import streamlit as st
import pandas as pd
import data as dl

def get_news():
    return dl.merged_news()

def _ago(iso):
    try:
        t = pd.Timestamp(iso)
        if t.tzinfo is not None:
            t = t.tz_convert(None)
        d = pd.Timestamp.now() - t
        h = d.total_seconds() / 3600
        return f"{int(d.total_seconds()//60)}m ago" if h < 1 else (f"{int(h)}h ago" if h < 48 else t.strftime("%b %d"))
    except Exception:
        return ""

def news_page(ctx):
    st.header("📰 NFL News")
    view = st.radio("Feed", ["All news", "🏥 Injuries & roster moves"], horizontal=True)
    items = get_news()
    if view != "All news":
        items = [i for i in items if dl.is_injury_news(i)]
    if not items:
        st.info("News feed unavailable right now — try again in a few minutes.")
        return
    # top stories with images as cards
    with_img = [i for i in items if i.get("img")]
    top = with_img[:3]
    if top:
        cols = st.columns(len(top))
        for col, it in zip(cols, top):
            with col:
                st.image(it["img"], width="stretch")
                badge = "🏥 " if dl.is_injury_news(it) else ""
                title = f"[{it['title']}]({it['link']})" if it.get("link") else it["title"]
                st.markdown(f"{badge}**{title}**")
                st.caption(f"{it['source']} · {_ago(it.get('published',''))}")
        top_keys = {" ".join(i["title"].lower().split())[:80] for i in top}
        items = [i for i in items if " ".join(i["title"].lower().split())[:80] not in top_keys]
        st.divider()
    st.caption(f"{len(items)} stories • ESPN + CBS • 🏥 = moves lines")
    for it in items:
        badge = "🏥 " if dl.is_injury_news(it) else ""
        title = f"[{it['title']}]({it['link']})" if it.get("link") else it["title"]
        st.markdown(f"{badge}**{title}**  \\n<small>{it['source']} · {_ago(it.get('published',''))}</small>",
                    unsafe_allow_html=True)
        if it.get("desc"):
            st.caption(it["desc"][:220])