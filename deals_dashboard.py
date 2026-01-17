"""
ShadowSnipe Deals Dashboard - Native Desktop App
Stealth arbitrage detection with AI-powered analysis.

Features:
- Always-on-top option
- Auto-refresh every few seconds
- Click to open eBay listing (newly listed, opens first result)
- Sound alerts for new snipes
- Thumbnail images
- Full reasoning display
- Clear margin/profit display
- Minimal, clean interface
- No browser needed

Requirements:
- Python 3.8+
- requests library (pip install requests)
- Pillow library (pip install Pillow) - for thumbnails
- No other dependencies (tkinter is built-in)

Usage:
1. Make sure your proxy is running at localhost:8000
2. Run: python deals_dashboard.py
"""

import tkinter as tk
from tkinter import ttk, messagebox
import requests
import webbrowser
import json
import threading
import time
from datetime import datetime
from io import BytesIO
import os
import base64
import re
import urllib.parse

# Try to import PIL for thumbnails
try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    print("Pillow not installed - thumbnails disabled. Run: pip install Pillow")

# Try to import winsound for alerts (Windows only)
try:
    import winsound
    SOUND_AVAILABLE = True
except ImportError:
    SOUND_AVAILABLE = False

# Configuration
PROXY_URL = "http://localhost:8000"
REFRESH_INTERVAL = 15  # seconds (was 5 - too aggressive)
ALWAYS_ON_TOP = True
WINDOW_WIDTH = 550
WINDOW_HEIGHT = 700
MAX_DEALS = 50  # Maximum deals to show
THUMBNAIL_SIZE = (80, 80)  # Bigger thumbnails

# Colors
COLORS = {
    'bg': '#1a1a2e',
    'panel': '#16213e',
    'buy': '#00ff88',
    'buy_bg': '#0a3320',
    'research': '#ffcc00',
    'research_bg': '#3d3a0a',
    'pass': '#ff4444',
    'text': '#e0e0e0',
    'text_dim': '#888888',
    'text_bright': '#ffffff',
    'border': '#333355',
    'hover': '#252550',
    'profit_positive': '#00ff88',
    'profit_negative': '#ff4444',
}


class Deal:
    """Represents a single deal"""
    def __init__(self, data):
        self.id = data.get('id', '')
        self.title = data.get('title', 'Unknown')
        self.price = data.get('total_price', 0)
        self.category = data.get('category', 'unknown')
        self.recommendation = data.get('recommendation', 'UNKNOWN')
        self.margin = data.get('margin', 'NA')
        self.confidence = data.get('confidence', 'NA')
        self.timestamp = data.get('timestamp', '')
        self.reasoning = data.get('reasoning', '')
        self.thumbnail_url = data.get('thumbnail', '')
        self.ebay_url = data.get('ebay_url', '')
        self.item_id = data.get('item_id', '')
        
        # Additional fields for enhanced display
        self.melt_value = data.get('melt_value', '')
        self.weight = data.get('weight', '')
        self.karat = data.get('karat', '')
        self.set_number = data.get('set_number', '')
        self.market_price = data.get('market_price', '')
        
    @property
    def margin_value(self):
        """Get margin as a float"""
        try:
            margin_str = str(self.margin).replace('$', '').replace('+', '').replace(',', '')
            return float(margin_str)
        except:
            return 0
            
    @property
    def margin_display(self):
        """Get formatted margin display"""
        try:
            val = self.margin_value
            if val >= 0:
                return f"+${val:.0f}"
            else:
                return f"-${abs(val):.0f}"
        except:
            return str(self.margin)
        
    @property
    def time_ago(self):
        """Return human-readable time since deal was found"""
        try:
            dt = datetime.fromisoformat(self.timestamp.replace('Z', '+00:00'))
            delta = datetime.now() - dt.replace(tzinfo=None)
            
            if delta.seconds < 60:
                return f"{delta.seconds}s ago"
            elif delta.seconds < 3600:
                return f"{delta.seconds // 60}m ago"
            else:
                return f"{delta.seconds // 3600}h ago"
        except:
            return ""
            
    @property
    def short_title(self):
        """Get shortened title for display"""
        return self.title[:55] + "..." if len(self.title) > 55 else self.title
        
    @property
    def ebay_search_url(self):
        """Get eBay search URL sorted by newly listed"""
        # Clean title for search
        search_query = self.title[:80]
        # Remove special characters that break search
        search_query = re.sub(r'[^\w\s\-]', ' ', search_query)
        search_query = ' '.join(search_query.split())  # Normalize whitespace
        
        # Build URL with "newly listed" sort (_sop=10)
        encoded = urllib.parse.quote(search_query)
        return f"https://www.ebay.com/sch/i.html?_nkw={encoded}&_sop=10"
        
    @property
    def ebay_first_result_url(self):
        """
        Get URL that will show the first newly listed result.
        We use a search with LH_BIN=1 (Buy It Now) and _sop=10 (newly listed)
        """
        search_query = self.title[:60]
        search_query = re.sub(r'[^\w\s\-]', ' ', search_query)
        search_query = ' '.join(search_query.split())
        
        encoded = urllib.parse.quote(search_query)
        # _sop=10 = newly listed, LH_BIN=1 = Buy It Now only
        return f"https://www.ebay.com/sch/i.html?_nkw={encoded}&_sop=10&LH_BIN=1"


class DealsApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("ShadowSnipe")
        self.root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        self.root.configure(bg=COLORS['bg'])
        
        # Set icon if available
        try:
            self.root.iconbitmap(default='')
        except:
            pass
        
        if ALWAYS_ON_TOP:
            self.root.attributes('-topmost', True)
        
        # Track seen deals for alerts
        self.seen_deals = set()
        self.deals = []
        self.running = True
        self.sound_enabled = True
        self.show_research = True
        self.thumbnail_cache = {}  # Cache for thumbnail images
        self.pause_until = 0  # Timestamp to pause refresh until
        
        # Build UI
        self._build_header()
        self._build_filters()
        self._build_deals_list()
        self._build_status_bar()
        
        # Start refresh thread
        self.refresh_thread = threading.Thread(target=self._refresh_loop, daemon=True)
        self.refresh_thread.start()
        
        # Initial fetch
        self.root.after(100, self._fetch_deals)
        
    def _build_header(self):
        """Build the header section"""
        header = tk.Frame(self.root, bg=COLORS['panel'], pady=10)
        header.pack(fill='x', padx=5, pady=5)
        
        # Title
        title = tk.Label(
            header, 
            text="👁️ ShadowSnipe", 
            font=('Segoe UI', 16, 'bold'),
            bg=COLORS['panel'],
            fg=COLORS['buy']
        )
        title.pack(side='left', padx=10)
        
        # Refresh button
        refresh_btn = tk.Button(
            header,
            text="⟳",
            font=('Segoe UI', 14),
            bg=COLORS['panel'],
            fg=COLORS['text'],
            relief='flat',
            command=self._fetch_deals,
            cursor='hand2'
        )
        refresh_btn.pack(side='right', padx=5)
        
        # Clear button
        clear_btn = tk.Button(
            header,
            text="🗑️",
            font=('Segoe UI', 14),
            bg=COLORS['panel'],
            fg=COLORS['text'],
            relief='flat',
            command=self._clear_deals,
            cursor='hand2'
        )
        clear_btn.pack(side='right', padx=5)
        
        # Settings button
        settings_btn = tk.Button(
            header,
            text="⚙",
            font=('Segoe UI', 14),
            bg=COLORS['panel'],
            fg=COLORS['text'],
            relief='flat',
            command=self._show_settings,
            cursor='hand2'
        )
        settings_btn.pack(side='right', padx=5)
        
    def _build_filters(self):
        """Build filter checkboxes"""
        filters = tk.Frame(self.root, bg=COLORS['bg'])
        filters.pack(fill='x', padx=10, pady=5)
        
        # Sound toggle
        self.sound_var = tk.BooleanVar(value=True)
        sound_cb = tk.Checkbutton(
            filters,
            text="🔊 Sound",
            variable=self.sound_var,
            bg=COLORS['bg'],
            fg=COLORS['text'],
            selectcolor=COLORS['panel'],
            activebackground=COLORS['bg'],
            command=self._toggle_sound
        )
        sound_cb.pack(side='left', padx=5)
        
        # Show RESEARCH toggle
        self.research_var = tk.BooleanVar(value=True)
        research_cb = tk.Checkbutton(
            filters,
            text="Show RESEARCH",
            variable=self.research_var,
            bg=COLORS['bg'],
            fg=COLORS['research'],
            selectcolor=COLORS['panel'],
            activebackground=COLORS['bg'],
            command=self._toggle_research
        )
        research_cb.pack(side='left', padx=5)
        
        # Always on top toggle
        self.ontop_var = tk.BooleanVar(value=ALWAYS_ON_TOP)
        ontop_cb = tk.Checkbutton(
            filters,
            text="Always on top",
            variable=self.ontop_var,
            bg=COLORS['bg'],
            fg=COLORS['text'],
            selectcolor=COLORS['panel'],
            activebackground=COLORS['bg'],
            command=self._toggle_ontop
        )
        ontop_cb.pack(side='left', padx=5)
        
    def _build_deals_list(self):
        """Build the scrollable deals list"""
        # Container frame
        container = tk.Frame(self.root, bg=COLORS['bg'])
        container.pack(fill='both', expand=True, padx=5, pady=5)
        
        # Canvas for scrolling
        self.canvas = tk.Canvas(container, bg=COLORS['bg'], highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient='vertical', command=self.canvas.yview)
        
        self.deals_frame = tk.Frame(self.canvas, bg=COLORS['bg'])
        
        self.canvas_window = self.canvas.create_window((0, 0), window=self.deals_frame, anchor='nw')
        
        self.canvas.configure(yscrollcommand=scrollbar.set)
        
        # Pack
        scrollbar.pack(side='right', fill='y')
        self.canvas.pack(side='left', fill='both', expand=True)
        
        # Bind events
        self.deals_frame.bind('<Configure>', self._on_frame_configure)
        self.canvas.bind('<Configure>', self._on_canvas_configure)
        
        # Mouse wheel scrolling
        self.canvas.bind_all('<MouseWheel>', self._on_mousewheel)
        
    def _build_status_bar(self):
        """Build the status bar"""
        self.status_bar = tk.Frame(self.root, bg=COLORS['panel'], height=30)
        self.status_bar.pack(fill='x', side='bottom')
        
        self.status_label = tk.Label(
            self.status_bar,
            text="Initializing network...",
            font=('Segoe UI', 9),
            bg=COLORS['panel'],
            fg=COLORS['text_dim']
        )
        self.status_label.pack(side='left', padx=10, pady=5)
        
        self.count_label = tk.Label(
            self.status_bar,
            text="",
            font=('Segoe UI', 9, 'bold'),
            bg=COLORS['panel'],
            fg=COLORS['text']
        )
        self.count_label.pack(side='right', padx=10, pady=5)
        
    def _on_frame_configure(self, event):
        """Update scroll region when frame size changes"""
        self.canvas.configure(scrollregion=self.canvas.bbox('all'))
        
    def _on_canvas_configure(self, event):
        """Update frame width when canvas size changes"""
        self.canvas.itemconfig(self.canvas_window, width=event.width)
        
    def _on_mousewheel(self, event):
        """Handle mouse wheel scrolling"""
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), 'units')
        
    def _toggle_sound(self):
        """Toggle sound alerts"""
        self.sound_enabled = self.sound_var.get()
        
    def _toggle_research(self):
        """Toggle showing RESEARCH deals"""
        self.show_research = self.research_var.get()
        self._update_display()
        
    def _toggle_ontop(self):
        """Toggle always on top"""
        self.root.attributes('-topmost', self.ontop_var.get())
    
    def _clear_deals(self):
        """Clear all deals from the display and server"""
        # Clear local state
        self.deals = []
        self.seen_deals.clear()
        self.thumbnail_cache.clear()
        self._update_display()
        self.count_label.config(text="🎯 0 SNIPES  👁️ 0 WATCHING")
        self._update_status("List cleared")
        
        # Also clear server-side deals
        try:
            requests.post(f"{PROXY_URL}/api/deals/clear", timeout=5)
        except:
            pass  # Server might not have this endpoint yet
        
        # Pause auto-refresh for 30 seconds so it doesn't immediately reload
        self.pause_until = time.time() + 30
        
    def _show_settings(self):
        """Show settings dialog"""
        messagebox.showinfo(
            "Settings",
            f"Proxy URL: {PROXY_URL}\n"
            f"Refresh: {REFRESH_INTERVAL}s\n"
            f"Max deals: {MAX_DEALS}\n"
            f"Thumbnails: {'Enabled' if PIL_AVAILABLE else 'Disabled (install Pillow)'}\n\n"
            "Edit deals_dashboard.py to change settings."
        )
        
    def _fetch_deals(self):
        """Fetch deals from proxy API"""
        try:
            # Use dedicated deals endpoint
            response = requests.get(
                f"{PROXY_URL}/api/deals", 
                params={'limit': MAX_DEALS, 'include_research': self.show_research},
                timeout=5
            )
            
            if response.status_code == 200:
                data = response.json()
                deals_data = data.get('deals', [])
                
                # Convert to Deal objects
                new_deals = []
                for listing in deals_data:
                    deal = Deal(listing)
                    new_deals.append(deal)
                    
                    # Check for new BUYs (for alerts)
                    if deal.id not in self.seen_deals and deal.recommendation == 'BUY':
                        self._alert_new_buy(deal)
                    self.seen_deals.add(deal.id)
                
                self.deals = new_deals
                self._update_display()
                self._update_status(f"Connected • Last update: {datetime.now().strftime('%H:%M:%S')}")
                
                # Update count from API response
                buy_count = data.get('buy_count', 0)
                research_count = data.get('research_count', 0)
                self.count_label.config(text=f"🎯 {buy_count} SNIPES  👁️ {research_count} WATCHING")
                
            else:
                self._update_status(f"Error: HTTP {response.status_code}")
                
        except requests.exceptions.ConnectionError:
            self._update_status("⚠ Network offline - is the proxy running?")
        except Exception as e:
            self._update_status(f"Error: {str(e)[:30]}")
            
    def _alert_new_buy(self, deal):
        """Alert user about new BUY deal"""
        if self.sound_enabled and SOUND_AVAILABLE:
            try:
                # Play system sound (Windows)
                winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
            except:
                pass  # Sound not available
                
        # Flash window
        try:
            self.root.bell()
            self.root.focus_force()
        except:
            pass
            
    def _load_thumbnail(self, url, deal_id):
        """Load thumbnail image from URL"""
        if not PIL_AVAILABLE or not url:
            return None
        
        # Must be HTTP URL
        if not url.startswith('http'):
            return None
            
        # Check cache
        if deal_id in self.thumbnail_cache:
            return self.thumbnail_cache[deal_id]
        
        # Limit cache size to prevent memory issues
        if len(self.thumbnail_cache) > 30:
            # Remove oldest entries
            keys_to_remove = list(self.thumbnail_cache.keys())[:10]
            for k in keys_to_remove:
                del self.thumbnail_cache[k]
            
        try:
            response = requests.get(url, timeout=3)
            if response.status_code == 200:
                img = Image.open(BytesIO(response.content))
                img.thumbnail(THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(img)
                self.thumbnail_cache[deal_id] = photo
                return photo
        except Exception as e:
            pass  # Silently fail - thumbnails are optional
            
        return None
            
    def _update_display(self):
        """Update the deals display"""
        # Clear existing widgets
        for widget in self.deals_frame.winfo_children():
            widget.destroy()
            
        if not self.deals:
            # Show empty state
            empty_label = tk.Label(
                self.deals_frame,
                text="Scanning the shadows...\n\nWaiting for targets\nfrom the network.",
                font=('Segoe UI', 11),
                bg=COLORS['bg'],
                fg=COLORS['text_dim'],
                justify='center'
            )
            empty_label.pack(pady=50)
            return
            
        # Filter deals
        filtered_deals = [
            d for d in self.deals 
            if d.recommendation == 'BUY' or (d.recommendation == 'RESEARCH' and self.show_research)
        ]
        
        # Create deal cards
        for deal in filtered_deals:
            self._create_deal_card(deal)
            
    def _create_deal_card(self, deal):
        """Create a card for a single deal"""
        # Determine colors based on recommendation
        if deal.recommendation == 'BUY':
            rec_color = COLORS['buy']
            border_color = '#00aa55'
            bg_color = COLORS['buy_bg']
        elif deal.recommendation == 'RESEARCH':
            rec_color = COLORS['research']
            border_color = '#aa8800'
            bg_color = COLORS['research_bg']
        else:
            rec_color = COLORS['text_dim']
            border_color = COLORS['border']
            bg_color = COLORS['panel']
            
        # Card frame
        card = tk.Frame(
            self.deals_frame,
            bg=bg_color,
            highlightbackground=border_color,
            highlightthickness=2,
            cursor='hand2'
        )
        card.pack(fill='x', padx=5, pady=4)
        
        # Bind click to open eBay
        card.bind('<Button-1>', lambda e, d=deal: self._open_deal(d))
        
        # === TOP ROW: Thumbnail + Main Info ===
        top_row = tk.Frame(card, bg=bg_color)
        top_row.pack(fill='x', padx=8, pady=(8, 4))
        top_row.bind('<Button-1>', lambda e, d=deal: self._open_deal(d))
        
        # Thumbnail (left side)
        if PIL_AVAILABLE and deal.thumbnail_url:
            # Create frame for thumbnail with fixed size
            thumb_frame = tk.Frame(top_row, bg=bg_color, width=85, height=85)
            thumb_frame.pack(side='left', padx=(0, 10))
            thumb_frame.pack_propagate(False)  # Prevent shrinking
            
            thumb_label = tk.Label(thumb_frame, bg=bg_color)
            thumb_label.pack(expand=True)
            thumb_label.bind('<Button-1>', lambda e, d=deal: self._open_deal(d))
            
            # Try to load thumbnail in background
            def load_thumb():
                photo = self._load_thumbnail(deal.thumbnail_url, deal.id)
                if photo:
                    try:
                        thumb_label.config(image=photo)
                        thumb_label.image = photo  # Keep reference
                    except:
                        pass
            threading.Thread(target=load_thumb, daemon=True).start()
        
        # Info container (right of thumbnail)
        info_frame = tk.Frame(top_row, bg=bg_color)
        info_frame.pack(side='left', fill='both', expand=True)
        info_frame.bind('<Button-1>', lambda e, d=deal: self._open_deal(d))
        
        # Header row (recommendation + category + time)
        header = tk.Frame(info_frame, bg=bg_color)
        header.pack(fill='x')
        header.bind('<Button-1>', lambda e, d=deal: self._open_deal(d))
        
        # Recommendation badge
        rec_label = tk.Label(
            header,
            text=f" {deal.recommendation} ",
            font=('Segoe UI', 10, 'bold'),
            bg=rec_color,
            fg='#000000'
        )
        rec_label.pack(side='left')
        rec_label.bind('<Button-1>', lambda e, d=deal: self._open_deal(d))
        
        # Category
        cat_label = tk.Label(
            header,
            text=f"  {deal.category.upper()}",
            font=('Segoe UI', 9),
            bg=bg_color,
            fg=COLORS['text_dim']
        )
        cat_label.pack(side='left')
        cat_label.bind('<Button-1>', lambda e, d=deal: self._open_deal(d))
        
        # Time
        time_label = tk.Label(
            header,
            text=deal.time_ago,
            font=('Segoe UI', 9),
            bg=bg_color,
            fg=COLORS['text_dim']
        )
        time_label.pack(side='right')
        time_label.bind('<Button-1>', lambda e, d=deal: self._open_deal(d))
        
        # Title
        title_label = tk.Label(
            info_frame,
            text=deal.short_title,
            font=('Segoe UI', 10),
            bg=bg_color,
            fg=COLORS['text_bright'],
            anchor='w',
            wraplength=WINDOW_WIDTH - 120
        )
        title_label.pack(fill='x', pady=(4, 2))
        title_label.bind('<Button-1>', lambda e, d=deal: self._open_deal(d))
        
        # === PRICE & MARGIN ROW ===
        price_row = tk.Frame(card, bg=bg_color)
        price_row.pack(fill='x', padx=8, pady=2)
        price_row.bind('<Button-1>', lambda e, d=deal: self._open_deal(d))
        
        # Price
        try:
            price_str = f"${float(str(deal.price).replace('$', '').replace(',', '')):.2f}"
        except:
            price_str = str(deal.price)
            
        price_label = tk.Label(
            price_row,
            text=f"💰 {price_str}",
            font=('Segoe UI', 11, 'bold'),
            bg=bg_color,
            fg=COLORS['text_bright']
        )
        price_label.pack(side='left')
        price_label.bind('<Button-1>', lambda e, d=deal: self._open_deal(d))
        
        # Margin (big and clear)
        margin_color = COLORS['profit_positive'] if deal.margin_value >= 0 else COLORS['profit_negative']
        margin_label = tk.Label(
            price_row,
            text=f"  📈 PROFIT: {deal.margin_display}  ",
            font=('Segoe UI', 11, 'bold'),
            bg=bg_color,
            fg=margin_color
        )
        margin_label.pack(side='left', padx=(15, 0))
        margin_label.bind('<Button-1>', lambda e, d=deal: self._open_deal(d))
        
        # Confidence
        conf_text = str(deal.confidence)
        if conf_text.lower() in ['high', 'h']:
            conf_color = COLORS['buy']
        elif conf_text.lower() in ['medium', 'med', 'm']:
            conf_color = COLORS['research']
        else:
            conf_color = COLORS['text_dim']
            
        conf_label = tk.Label(
            price_row,
            text=f"Conf: {conf_text}",
            font=('Segoe UI', 9),
            bg=bg_color,
            fg=conf_color
        )
        conf_label.pack(side='right')
        conf_label.bind('<Button-1>', lambda e, d=deal: self._open_deal(d))
        
        # === REASONING ROW ===
        if deal.reasoning:
            # Clean up reasoning text
            reasoning_text = deal.reasoning.replace('[SERVER:', '\n[SERVER:').strip()
            reasoning_text = reasoning_text[:250] + "..." if len(reasoning_text) > 250 else reasoning_text
            
            reason_label = tk.Label(
                card,
                text=reasoning_text,
                font=('Segoe UI', 8),
                bg=bg_color,
                fg=COLORS['text_dim'],
                anchor='w',
                justify='left',
                wraplength=WINDOW_WIDTH - 40
            )
            reason_label.pack(fill='x', padx=8, pady=(2, 8))
            reason_label.bind('<Button-1>', lambda e, d=deal: self._open_deal(d))
        
    def _open_deal(self, deal):
        """Open the deal in browser - newly listed eBay search"""
        # Use the newly listed search URL
        url = deal.ebay_first_result_url
        webbrowser.open(url)
        
    def _update_status(self, text):
        """Update status bar text"""
        self.status_label.config(text=text)
        
    def _refresh_loop(self):
        """Background thread for auto-refresh"""
        while self.running:
            time.sleep(REFRESH_INTERVAL)
            if self.running:
                # Check if we're paused (after clear)
                if time.time() < self.pause_until:
                    continue
                # Schedule fetch on main thread
                self.root.after(0, self._fetch_deals)
                
    def run(self):
        """Start the application"""
        # Handle window close
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.mainloop()
        
    def _on_close(self):
        """Handle window close"""
        self.running = False
        self.root.destroy()


def main():
    print("=" * 50)
    print("  ShadowSnipe • Stealth Arbitrage Detection")
    print("=" * 50)
    print(f"Connecting to network at {PROXY_URL}")
    print(f"Thumbnails: {'Enabled' if PIL_AVAILABLE else 'Disabled'}")
    print(f"Sound alerts: {'Enabled' if SOUND_AVAILABLE else 'Disabled'}")
    print("Press Ctrl+C or close window to exit")
    print()
    
    app = DealsApp()
    app.run()


if __name__ == "__main__":
    main()
