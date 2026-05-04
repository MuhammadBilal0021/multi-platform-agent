import sys
import os
import pandas as pd
import streamlit as st

# Add project root to path so 'core' module is found
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.memory import get_all_logs

# =============================================================================
# PAGE CONFIGURATION
# =============================================================================
st.set_page_config(
    page_title="OmniAgent Dashboard",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS for a darker, sleeker sci-fi look
st.markdown("""
<style>
    .stApp {
        background-color: #0E1117;
        color: #FAFAFA;
    }
    h1, h2, h3 {
        color: #5865F2; /* Blurple accent */
        font-family: 'Inter', sans-serif;
    }
    .metric-card {
        background-color: #1A1C23;
        padding: 20px;
        border-radius: 10px;
        border: 1px solid #2E303E;
        text-align: center;
        box-shadow: 0 4px 6px rgba(0,0,0,0.3);
    }
    .metric-value {
        font-size: 2rem;
        font-weight: bold;
        color: #00E5FF;
    }
    .metric-label {
        font-size: 1rem;
        color: #A0AEC0;
        text-transform: uppercase;
        letter-spacing: 1px;
    }
</style>
""", unsafe_allow_html=True)


# =============================================================================
# DATA LOADING
# =============================================================================
@st.cache_data(ttl=5)  # Cache for 5 seconds to prevent spamming SQLite
def load_data():
    logs = get_all_logs(limit=1000)
    if not logs:
        return pd.DataFrame()
    
    df = pd.DataFrame(logs)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    return df

# =============================================================================
# MAIN UI
# =============================================================================
st.title("🧠 OmniAgent Command Center")
st.markdown("Live monitoring for your Multi-Platform AI Agent.")

df = load_data()

if df.empty:
    st.info("No logs found. Start chatting with the agent to populate data!")
else:
    # --- METRICS ROW ---
    total_messages = len(df)
    unique_users = df['user_id'].nunique()
    active_platforms = df['channel'].nunique()
    
    # We count "assistant" messages as completed tasks
    agent_replies = len(df[df['role'] == 'assistant'])
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.markdown(f"""
            <div class="metric-card">
                <div class="metric-value">{total_messages}</div>
                <div class="metric-label">Total Messages</div>
            </div>
        """, unsafe_allow_html=True)
        
    with col2:
        st.markdown(f"""
            <div class="metric-card">
                <div class="metric-value">{agent_replies}</div>
                <div class="metric-label">Agent Replies</div>
            </div>
        """, unsafe_allow_html=True)
        
    with col3:
        st.markdown(f"""
            <div class="metric-card">
                <div class="metric-value">{unique_users}</div>
                <div class="metric-label">Unique Users</div>
            </div>
        """, unsafe_allow_html=True)
        
    with col4:
        st.markdown(f"""
            <div class="metric-card">
                <div class="metric-value">{active_platforms}</div>
                <div class="metric-label">Active Platforms</div>
            </div>
        """, unsafe_allow_html=True)
        
    st.write("---")
    
    # --- CHARTS ROW ---
    colA, colB = st.columns(2)
    
    with colA:
        st.subheader("Platform Activity")
        platform_counts = df['channel'].value_counts().reset_index()
        platform_counts.columns = ['Platform', 'Messages']
        st.bar_chart(platform_counts.set_index('Platform'))
        
    with colB:
        st.subheader("Message Timeline (Last 1000)")
        # Resample by hour or minute depending on data
        timeline = df.set_index('timestamp').resample('1h').size()
        st.line_chart(timeline)
        
    st.write("---")
    
    # --- LOG VIEWER ---
    st.subheader("📡 Live Communication Feed")
    
    # Filters
    f_col1, f_col2 = st.columns(2)
    with f_col1:
        selected_channel = st.selectbox("Filter by Platform", ["All"] + list(df['channel'].unique()))
    with f_col2:
        selected_role = st.selectbox("Filter by Role", ["All", "user", "assistant"])
        
    # Apply filters
    filtered_df = df.copy()
    if selected_channel != "All":
        filtered_df = filtered_df[filtered_df['channel'] == selected_channel]
    if selected_role != "All":
        filtered_df = filtered_df[filtered_df['role'] == selected_role]
        
    # Display table (hide ID column if it exists, format timestamp)
    display_df = filtered_df.sort_values('timestamp', ascending=False).head(100)
    st.dataframe(
        display_df[['timestamp', 'channel', 'role', 'user_id', 'content']],
        use_container_width=True,
        hide_index=True
    )

    # Auto-refresh button
    if st.button("🔄 Refresh Data"):
        st.rerun()
