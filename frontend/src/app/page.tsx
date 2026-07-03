"use client";

import React, { useState, useEffect } from "react";
import { 
  BarChart, 
  MapPin, 
  Flame, 
  Target, 
  RefreshCw, 
  Search, 
  SlidersHorizontal, 
  Activity, 
  Clipboard, 
  Check, 
  ChevronDown, 
  ChevronUp, 
  BookOpen, 
  TrendingUp, 
  Database,
  ExternalLink,
  X
} from "lucide-react";

interface Post {
  id: string;
  url: string;
  title: string;
  body: string;
  relevance_score: number;
  pain_score: number;
  emotion_score: number;
  subreddit: string;
  created_utc: number;
  processed_at: string;
  user_intent: string;
  marketing_campaign: string;
  suggested_response: string;
  country: string;
  state: string;
  city: string;
  origin: string;
  destination: string;
  priority_level: string;
  overall_priority_score: number;
  intent_strength: number;
  pain_severity: number;
}

export default function Home() {
  const [posts, setPosts] = useState<Post[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshStep, setRefreshStep] = useState("");
  const [selectedPost, setSelectedPost] = useState<Post | null>(null);

  // Filters State
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedCity, setSelectedCity] = useState("All");
  const [selectedCampaign, setSelectedCampaign] = useState("All");
  const [selectedPriority, setSelectedPriority] = useState("All");
  const [minRelevance, setMinRelevance] = useState(0);
  const [minFrustration, setMinFrustration] = useState(0);
  const [minPriority, setMinPriority] = useState(0);

  // Sorting State
  const [sortBy, setSortBy] = useState<keyof Post>("overall_priority_score");
  const [sortOrder, setSortOrder] = useState<"desc" | "asc">("desc");

  // Sidebar Collapse Toggles
  const [geographyOpen, setGeographyOpen] = useState(true);
  const [scoresOpen, setScoresOpen] = useState(true);
  const [searchOpen, setSearchOpen] = useState(true);

  // Toast status feedback
  const [toastMessage, setToastMessage] = useState("");
  const [copiedId, setCopiedId] = useState(false);

  // Fetch API Base URL
  const API_URL = "http://127.0.0.1:8000";

  const fetchPosts = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_URL}/api/posts`);
      if (res.ok) {
        const data = await res.json();
        setPosts(data);
        if (data.length > 0 && !selectedPost) {
          setSelectedPost(data[0]);
        }
      }
    } catch (err) {
      console.error("Failed to fetch posts:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchPosts();
  }, []);

  const triggerRefresh = async () => {
    setRefreshing(true);
    setRefreshStep("Synchronizing with SQLite database...");
    await new Promise((r) => setTimeout(r, 600));
    await fetchPosts();
    setRefreshing(false);
    showToast("Dashboard synchronized with SQLite database.");
  };

  const showToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(""), 3000);
  };

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedId(true);
    showToast("Suggested reply copied to clipboard!");
    setTimeout(() => setCopiedId(false), 2000);
  };

  // Filter & Sort Discussions
  const filteredPosts = posts.filter((post) => {
    // Search query
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      const match = 
        post.title.toLowerCase().includes(q) ||
        post.body.toLowerCase().includes(q) ||
        post.city.toLowerCase().includes(q) ||
        post.marketing_campaign.toLowerCase().includes(q) ||
        post.user_intent.toLowerCase().includes(q);
      if (!match) return false;
    }

    // City constraint (Locked to India / Delhi NCR operating region)
    if (selectedCity !== "All" && post.city !== selectedCity) return false;

    // Campaign Category
    if (selectedCampaign !== "All" && post.marketing_campaign !== selectedCampaign) return false;

    // Priority Level
    if (selectedPriority !== "All" && post.priority_level !== selectedPriority) return false;

    // Ranges
    if (post.relevance_score < minRelevance) return false;
    if (post.emotion_score < minFrustration) return false;
    if (post.overall_priority_score < minPriority) return false;

    return true;
  }).sort((a, b) => {
    const valA = a[sortBy] ?? 0;
    const valB = b[sortBy] ?? 0;
    if (valA < valB) return sortOrder === "desc" ? 1 : -1;
    if (valA > valB) return sortOrder === "desc" ? -1 : 1;
    return 0;
  });

  // Calculate KPIs
  const totalPosts = filteredPosts.length;
  const newToday = filteredPosts.filter((p) => {
    const today = new Date().toISOString().split("T")[0];
    return p.processed_at === today;
  }).length;

  const delhiPosts = filteredPosts.filter((p) => p.city.toLowerCase() === "delhi").length;
  const noidaPosts = filteredPosts.filter((p) => p.city.toLowerCase().includes("noida")).length;
  const gurugramPosts = filteredPosts.filter((p) => p.city.toLowerCase().includes("gurugram") || p.city.toLowerCase().includes("gurgaon")).length;
  
  const avgRelevance = filteredPosts.length > 0 
    ? filteredPosts.reduce((acc, p) => acc + p.relevance_score, 0) / filteredPosts.length 
    : 0;

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-[#0F172A] text-slate-100 font-sans">
      
      {/* 1. SIDEBAR (collapsible filters, Notion-like style) */}
      <aside className="w-80 border-r border-slate-800 bg-[#0B0F19] flex flex-col overflow-y-auto shrink-0 select-none">
        
        {/* Brand logo details */}
        <div className="p-6 border-b border-slate-800 flex items-center gap-3">
          <div className="bg-blue-600 p-2 rounded-xl text-white">
            <Activity size={20} />
          </div>
          <div>
            <h2 className="font-extrabold text-base tracking-tight text-white">SaaS Control Center</h2>
            <p className="text-[10px] text-slate-500 font-semibold uppercase tracking-wider">Campaign Settings</p>
          </div>
        </div>

        {/* Filters Groups */}
        <div className="flex-1 p-4 space-y-4">
          
          {/* SEARCH BOX */}
          <div className="border border-slate-800 rounded-xl bg-[#131b2e] p-3">
            <div className="flex items-center gap-2 text-slate-400">
              <Search size={14} />
              <input 
                type="text" 
                placeholder="Search target posts..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="bg-transparent border-none outline-none text-xs text-slate-200 placeholder-slate-500 w-full"
              />
              {searchQuery && (
                <button onClick={() => setSearchQuery("")} className="hover:text-white">
                  <X size={12} />
                </button>
              )}
            </div>
          </div>

          {/* Collapsible GEOGRAPHY */}
          <div className="border border-slate-800/80 rounded-xl overflow-hidden">
            <button 
              onClick={() => setGeographyOpen(!geographyOpen)}
              className="w-full flex items-center justify-between p-3 bg-slate-900/40 text-xs font-bold text-slate-400 hover:text-white"
            >
              <span className="flex items-center gap-2"><MapPin size={12} />📍 Geography</span>
              {geographyOpen ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
            </button>
            {geographyOpen && (
              <div className="p-3 bg-slate-950/20 border-t border-slate-800/50 space-y-2">
                <div>
                  <label className="text-[10px] uppercase font-bold text-slate-500">Country</label>
                  <select disabled className="w-full bg-slate-900 border border-slate-800 rounded-lg p-2 text-xs mt-1 text-slate-400 cursor-not-allowed">
                    <option>India</option>
                  </select>
                </div>
                <div>
                  <label className="text-[10px] uppercase font-bold text-slate-500">State</label>
                  <select disabled className="w-full bg-slate-900 border border-slate-800 rounded-lg p-2 text-xs mt-1 text-slate-400 cursor-not-allowed">
                    <option>Delhi NCR</option>
                  </select>
                </div>
                <div>
                  <label className="text-[10px] uppercase font-bold text-slate-500">City</label>
                  <select 
                    value={selectedCity} 
                    onChange={(e) => setSelectedCity(e.target.value)}
                    className="w-full bg-slate-900 border border-slate-800 rounded-lg p-2 text-xs mt-1 text-slate-200"
                  >
                    <option value="All">All Cities</option>
                    <option value="Delhi">Delhi</option>
                    <option value="Noida">Noida</option>
                    <option value="Greater Noida">Greater Noida</option>
                    <option value="Gurugram">Gurugram</option>
                    <option value="Ghaziabad">Ghaziabad</option>
                    <option value="Faridabad">Faridabad</option>
                  </select>
                </div>
              </div>
            )}
          </div>

          {/* Collapsible AI SCORES */}
          <div className="border border-slate-800/80 rounded-xl overflow-hidden">
            <button 
              onClick={() => setScoresOpen(!scoresOpen)}
              className="w-full flex items-center justify-between p-3 bg-slate-900/40 text-xs font-bold text-slate-400 hover:text-white"
            >
              <span className="flex items-center gap-2"><Flame size={12} />🎯 AI Score Metrics</span>
              {scoresOpen ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
            </button>
            {scoresOpen && (
              <div className="p-3 bg-slate-950/20 border-t border-slate-800/50 space-y-3">
                <div>
                  <label className="text-[10px] uppercase font-bold text-slate-500">Marketing Campaign</label>
                  <select 
                    value={selectedCampaign}
                    onChange={(e) => setSelectedCampaign(e.target.value)}
                    className="w-full bg-slate-900 border border-slate-800 rounded-lg p-2 text-xs mt-1 text-slate-200"
                  >
                    <option value="All">All Categories</option>
                    <option value="Student Commute">Student Commute</option>
                    <option value="Office Commute">Office Commute</option>
                    <option value="Carpool Promotion">Carpool Promotion</option>
                    <option value="Fuel Savings">Fuel Savings</option>
                    <option value="Traffic & Congestion">Traffic & Congestion</option>
                    <option value="Public Transport">Public Transport</option>
                    <option value="General Transportation">General Transportation</option>
                  </select>
                </div>
                <div>
                  <label className="text-[10px] uppercase font-bold text-slate-500">Priority Level</label>
                  <select 
                    value={selectedPriority}
                    onChange={(e) => setSelectedPriority(e.target.value)}
                    className="w-full bg-slate-900 border border-slate-800 rounded-lg p-2 text-xs mt-1 text-slate-200"
                  >
                    <option value="All">All Priorities</option>
                    <option value="Highest">Highest</option>
                    <option value="Medium">Medium</option>
                    <option value="Low">Low</option>
                  </select>
                </div>
                <div className="space-y-1">
                  <div className="flex justify-between text-[10px] uppercase font-bold text-slate-500">
                    <span>Min Relevance</span>
                    <span className="text-blue-500">{minRelevance.toFixed(1)}</span>
                  </div>
                  <input 
                    type="range" min="0" max="10" step="0.5" 
                    value={minRelevance} 
                    onChange={(e) => setMinRelevance(parseFloat(e.target.value))}
                    className="w-full accent-blue-600 h-1 bg-slate-800 rounded-lg appearance-none cursor-pointer"
                  />
                </div>
                <div className="space-y-1">
                  <div className="flex justify-between text-[10px] uppercase font-bold text-slate-500">
                    <span>Min Frustration</span>
                    <span className="text-red-500">{minFrustration.toFixed(1)}</span>
                  </div>
                  <input 
                    type="range" min="0" max="10" step="0.5" 
                    value={minFrustration} 
                    onChange={(e) => setMinFrustration(parseFloat(e.target.value))}
                    className="w-full accent-blue-600 h-1 bg-slate-800 rounded-lg appearance-none cursor-pointer"
                  />
                </div>
              </div>
            )}
          </div>

          {/* Collapsible SORTING ENGINE */}
          <div className="border border-slate-800/80 rounded-xl overflow-hidden">
            <button 
              onClick={() => setSearchOpen(!searchOpen)}
              className="w-full flex items-center justify-between p-3 bg-slate-900/40 text-xs font-bold text-slate-400 hover:text-white"
            >
              <span className="flex items-center gap-2"><SlidersHorizontal size={12} />🔀 Sorting Engine</span>
              {searchOpen ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
            </button>
            {searchOpen && (
              <div className="p-3 bg-slate-950/20 border-t border-slate-800/50 space-y-2">
                <div>
                  <label className="text-[10px] uppercase font-bold text-slate-500">Sort By</label>
                  <select 
                    value={sortBy}
                    onChange={(e) => setSortBy(e.target.value as keyof Post)}
                    className="w-full bg-slate-900 border border-slate-800 rounded-lg p-2 text-xs mt-1 text-slate-200"
                  >
                    <option value="overall_priority_score">Priority Score</option>
                    <option value="relevance_score">Relevance Score</option>
                    <option value="emotion_score">Frustration Score</option>
                    <option value="created_utc">Scrape Date</option>
                  </select>
                </div>
                <div>
                  <label className="text-[10px] uppercase font-bold text-slate-500">Direction</label>
                  <div className="flex gap-2 mt-1">
                    <button 
                      onClick={() => setSortOrder("desc")}
                      className={`flex-1 text-xs py-1.5 rounded-lg font-bold border transition ${
                        sortOrder === "desc" 
                          ? "bg-blue-600/10 border-blue-500 text-blue-400" 
                          : "border-slate-800 hover:border-slate-700 text-slate-400"
                      }`}
                    >
                      Descending
                    </button>
                    <button 
                      onClick={() => setSortOrder("asc")}
                      className={`flex-1 text-xs py-1.5 rounded-lg font-bold border transition ${
                        sortOrder === "asc" 
                          ? "bg-blue-600/10 border-blue-500 text-blue-400" 
                          : "border-slate-800 hover:border-slate-700 text-slate-400"
                      }`}
                    >
                      Ascending
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>

        </div>
      </aside>

      {/* 2. MAIN LAYOUT AREA */}
      <main className="flex-1 flex flex-col overflow-hidden">
        
        {/* TOP NAVIGATION BAR */}
        <header className="h-20 border-b border-slate-800 px-8 flex items-center justify-between shrink-0 bg-slate-900/20 backdrop-blur-md">
          <div className="flex items-center gap-3">
            <div>
              <h1 className="font-extrabold text-xl text-white tracking-tight">Snapgo</h1>
              <p className="text-xs text-slate-400">Reddit Marketing Intelligence Platform</p>
            </div>
          </div>
          
          <div className="flex items-center gap-4">
            <div className="text-right">
              <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span>
                Live Status: Active
              </span>
              <p className="text-[10px] text-slate-500 mt-1">Syncing every hour</p>
            </div>
            
            <button 
              onClick={triggerRefresh}
              disabled={refreshing}
              className="flex items-center gap-2 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-800/40 text-white font-bold text-xs py-2 px-4 rounded-xl shadow-lg shadow-blue-500/10 transition"
            >
              <RefreshCw size={14} className={refreshing ? "animate-spin" : ""} />
              {refreshing ? "Syncing..." : "Sync Database"}
            </button>
          </div>
        </header>

        {/* METRICS & LIST SPLIT SECTION */}
        <div className="flex-1 overflow-y-auto p-8 space-y-6">
          
          {/* KPI CARDS GRID */}
          <section className="grid grid-cols-6 gap-4">
            
            {/* KPI Card 1 */}
            <div className="bg-[#1E293B] border border-slate-800/60 p-4 rounded-2xl shadow-md transition hover:-translate-y-0.5 hover:border-blue-500/30">
              <div className="flex justify-between items-center text-slate-400 mb-1.5">
                <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500">Total Scraped</span>
                <span className="p-1 bg-slate-800 rounded-lg"><Database size={12} /></span>
              </div>
              <div className="text-2xl font-black text-white">{totalPosts}</div>
              <p className="text-[9px] text-slate-500 mt-0.5">Matching active filters</p>
            </div>

            {/* KPI Card 2 */}
            <div className="bg-[#1E293B] border border-slate-800/60 p-4 rounded-2xl shadow-md transition hover:-translate-y-0.5 hover:border-blue-500/30">
              <div className="flex justify-between items-center text-slate-400 mb-1.5">
                <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500">New Today</span>
                <span className="p-1 bg-slate-800 rounded-lg text-blue-400"><TrendingUp size={12} /></span>
              </div>
              <div className="text-2xl font-black text-white">{newToday}</div>
              <p className="text-[9px] text-slate-500 mt-0.5">Scraped today (IST)</p>
            </div>

            {/* KPI Card 3 */}
            <div className="bg-[#1E293B] border border-slate-800/60 p-4 rounded-2xl shadow-md transition hover:-translate-y-0.5 hover:border-blue-500/30">
              <div className="flex justify-between items-center text-slate-400 mb-1.5">
                <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500">Delhi Posts</span>
                <span className="p-1 bg-slate-800 rounded-lg"><MapPin size={12} /></span>
              </div>
              <div className="text-2xl font-black text-white">{delhiPosts}</div>
              <p className="text-[9px] text-slate-500 mt-0.5">Delhi operational hub</p>
            </div>

            {/* KPI Card 4 */}
            <div className="bg-[#1E293B] border border-slate-800/60 p-4 rounded-2xl shadow-md transition hover:-translate-y-0.5 hover:border-blue-500/30">
              <div className="flex justify-between items-center text-slate-400 mb-1.5">
                <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500">Noida Posts</span>
                <span className="p-1 bg-slate-800 rounded-lg"><MapPin size={12} /></span>
              </div>
              <div className="text-2xl font-black text-white">{noidaPosts}</div>
              <p className="text-[9px] text-slate-500 mt-0.5">Noida & Greater Noida</p>
            </div>

            {/* KPI Card 5 */}
            <div className="bg-[#1E293B] border border-slate-800/60 p-4 rounded-2xl shadow-md transition hover:-translate-y-0.5 hover:border-blue-500/30">
              <div className="flex justify-between items-center text-slate-400 mb-1.5">
                <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500">Gurugram Posts</span>
                <span className="p-1 bg-slate-800 rounded-lg"><MapPin size={12} /></span>
              </div>
              <div className="text-2xl font-black text-white">{gurugramPosts}</div>
              <p className="text-[9px] text-slate-500 mt-0.5">Gurugram & Gurgaon</p>
            </div>

            {/* KPI Card 6 */}
            <div className="bg-[#1E293B] border border-slate-800/60 p-4 rounded-2xl shadow-md transition hover:-translate-y-0.5 hover:border-blue-500/30">
              <div className="flex justify-between items-center text-slate-400 mb-1.5">
                <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500">Avg Relevance</span>
                <span className="p-1 bg-slate-800 rounded-lg text-emerald-400"><Target size={12} /></span>
              </div>
              <div className="text-2xl font-black text-white">{avgRelevance.toFixed(1)}/10</div>
              <p className="text-[9px] text-slate-500 mt-0.5">Transit context score</p>
            </div>

          </section>

          {/* SPLIT VIEW LIST + DETAIL */}
          <div className="grid grid-cols-10 gap-6 items-start">
            
            {/* LEFT FEED (65% width) */}
            <div className="col-span-6 space-y-3">
              <h3 className="font-bold text-sm text-slate-400 mb-4">Discovered target posts ({totalPosts})</h3>
              
              {loading ? (
                <div className="space-y-3">
                  {[1, 2, 3].map((n) => (
                    <div key={n} className="bg-[#1E293B]/40 border border-slate-800 p-6 rounded-2xl animate-pulse space-y-4">
                      <div className="h-4 bg-slate-800 rounded-lg w-1/3"></div>
                      <div className="h-6 bg-slate-800 rounded-lg w-3/4"></div>
                      <div className="h-4 bg-slate-800 rounded-lg w-1/2"></div>
                    </div>
                  ))}
                </div>
              ) : filteredPosts.length === 0 ? (
                <div className="bg-[#1E293B] border border-slate-800/60 rounded-2xl p-12 text-center">
                  <span className="text-4xl">🔍</span>
                  <h4 className="text-white font-bold text-base mt-4">No matching posts found</h4>
                  <p className="text-xs text-slate-400 mt-2 max-w-sm mx-auto">Adjust your relevance/frustration filters or search keywords in the sidebar.</p>
                </div>
              ) : (
                filteredPosts.map((post) => (
                  <div 
                    key={post.id}
                    onClick={() => setSelectedPost(post)}
                    className={`bg-[#1E293B] border p-6 rounded-2xl shadow-md transition cursor-pointer select-none ${
                      selectedPost?.id === post.id 
                        ? "border-blue-500 bg-[#202e47]" 
                        : "border-slate-800/60 hover:border-slate-700/60"
                    }`}
                  >
                    <div className="flex flex-wrap items-center gap-2 mb-3">
                      <span className="px-2 py-0.5 rounded-full text-[9px] font-bold bg-blue-500/10 text-blue-400 border border-blue-500/20">🏙️ {post.city}</span>
                      <span className={`px-2 py-0.5 rounded-full text-[9px] font-bold border ${
                        post.priority_level === "Highest" || post.priority_level === "High"
                          ? "bg-red-500/10 text-red-400 border-red-500/20"
                          : post.priority_level === "Medium"
                            ? "bg-amber-500/10 text-amber-400 border-amber-500/20"
                            : "bg-slate-500/10 text-slate-400 border-slate-500/20"
                      }`}>⚡ {post.priority_level} Priority</span>
                      <span className="px-2 py-0.5 rounded-full text-[9px] font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">🎯 {post.marketing_campaign}</span>
                    </div>

                    <h4 className="font-extrabold text-sm text-white leading-snug mb-2">{post.title}</h4>
                    <p className="text-xs text-slate-400 line-clamp-2 leading-relaxed mb-4">{post.body}</p>

                    <div className="flex items-center justify-between text-[10px] text-slate-500">
                      <div className="flex gap-4">
                        <span>Relevance: <strong className="text-slate-300 font-semibold">{post.relevance_score.toFixed(1)}</strong></span>
                        <span>Frustration: <strong className="text-slate-300 font-semibold">{post.emotion_score.toFixed(1)}</strong></span>
                      </div>
                      <span>r/{post.subreddit}</span>
                    </div>
                  </div>
                ))
              )}
            </div>

            {/* RIGHT DETAILS PANEL (35% width) */}
            <div className="col-span-4 sticky top-6">
              <h3 className="font-bold text-sm text-slate-400 mb-4">Discussion details</h3>

              {selectedPost ? (
                <div className="bg-[#1E293B] border border-slate-800 p-6 rounded-2xl shadow-xl space-y-6">
                  
                  {/* Title Header */}
                  <div className="border-b border-slate-800 pb-4">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-[10px] uppercase font-black text-blue-500 tracking-wider">Target Insight</span>
                      <a 
                        href={selectedPost.url} 
                        target="_blank" 
                        rel="noreferrer"
                        className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-white transition"
                      >
                        <ExternalLink size={12} />
                        Original post
                      </a>
                    </div>
                    <h3 className="font-extrabold text-base text-white leading-snug">{selectedPost.title}</h3>
                  </div>

                  {/* Body Content */}
                  <div className="space-y-2">
                    <span className="text-[10px] uppercase font-bold text-slate-500">Post Text</span>
                    <p className="text-xs text-slate-300 bg-slate-950/40 p-4 rounded-xl border border-slate-800/80 leading-relaxed max-h-48 overflow-y-auto">
                      {selectedPost.body || <em className="text-slate-500">No post body text.</em>}
                    </p>
                  </div>

                  {/* Meta Details */}
                  <div className="grid grid-cols-2 gap-4 text-xs">
                    <div>
                      <span className="text-[10px] uppercase font-bold text-slate-500 block">User Intent</span>
                      <span className="font-semibold text-slate-200 block mt-0.5">{selectedPost.user_intent}</span>
                    </div>
                    <div>
                      <span className="text-[10px] uppercase font-bold text-slate-500 block">Campaign Group</span>
                      <span className="font-semibold text-slate-200 block mt-0.5">{selectedPost.marketing_campaign}</span>
                    </div>
                    <div>
                      <span className="text-[10px] uppercase font-bold text-slate-500 block">Operating City</span>
                      <span className="font-semibold text-slate-200 block mt-0.5">{selectedPost.city}</span>
                    </div>
                    <div>
                      <span className="text-[10px] uppercase font-bold text-slate-500 block">Subreddit</span>
                      <span className="font-semibold text-slate-200 block mt-0.5">r/{selectedPost.subreddit}</span>
                    </div>
                  </div>

                  {/* AI Response Card */}
                  <div className="bg-blue-600/5 border border-blue-500/20 p-5 rounded-xl space-y-3">
                    <span className="text-[10px] uppercase font-bold text-blue-400 tracking-wider flex items-center gap-1.5">
                      🤖 AI Suggested Response
                    </span>
                    <p className="text-xs text-slate-200 leading-relaxed bg-[#0F172A] p-3 rounded-lg border border-slate-800/60">
                      {selectedPost.suggested_response || "AI response unavailable."}
                    </p>
                    {selectedPost.suggested_response && (
                      <button 
                        onClick={() => copyToClipboard(selectedPost.suggested_response)}
                        className="flex items-center gap-1.5 text-xs text-blue-400 hover:text-blue-300 font-semibold transition"
                      >
                        {copiedId ? <Check size={12} /> : <Clipboard size={12} />}
                        {copiedId ? "Copied!" : "Copy reply draft"}
                      </button>
                    )}
                  </div>

                </div>
              ) : (
                <div className="bg-[#1E293B]/40 border border-slate-800 p-12 rounded-2xl text-center text-slate-500 text-xs">
                  Select a discussion card to view its AI insights and copy draft suggestions.
                </div>
              )}
            </div>

          </div>

        </div>

      </main>

      {/* REFRESHING OVERLAY MODAL */}
      {refreshing && (
        <div className="fixed inset-0 bg-slate-950/80 backdrop-blur-sm flex items-center justify-center z-50 animate-fade-in">
          <div className="bg-[#1E293B] border border-slate-800/80 p-8 rounded-2xl shadow-2xl text-center max-w-sm w-full space-y-6">
            <div className="relative flex items-center justify-center">
              <RefreshCw size={36} className="text-blue-500 animate-spin" />
            </div>
            <div className="space-y-1.5">
              <h3 className="font-black text-base text-white">Syncing Live Data</h3>
              <p className="text-xs text-slate-400">{refreshStep}</p>
            </div>
            <div className="w-full bg-slate-900 h-1.5 rounded-full overflow-hidden">
              <div className="bg-blue-600 h-full w-2/3 rounded-full animate-pulse"></div>
            </div>
          </div>
        </div>
      )}

      {/* TOAST POPUP NOTIFICATION */}
      {toastMessage && (
        <div className="fixed bottom-6 right-6 bg-slate-900 border border-slate-800 px-4 py-3 rounded-xl shadow-2xl flex items-center gap-2 text-xs font-semibold text-slate-200 z-50 animate-slide-in">
          <Check size={14} className="text-emerald-400" />
          {toastMessage}
        </div>
      )}

    </div>
  );
}
