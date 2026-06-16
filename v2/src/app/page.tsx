"use client";

import { useEffect, useState } from "react";
import { ArrowRight, Disc, ListMusic, RefreshCw } from "lucide-react";

/* Hallmark · macrostructure: Workbench · nav: N5 Floating Pill · theme: Cobalt */

export default function Home() {
  const [authStatus, setAuthStatus] = useState<{ old: boolean; new: boolean } | null>(null);

  useEffect(() => {
    fetch("/api/auth/status")
      .then((res) => res.json())
      .then((data) => setAuthStatus(data))
      .catch((err) => console.error(err));
  }, []);

  if (!authStatus) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-paper-1">
        <RefreshCw className="w-6 h-6 animate-spin text-accent" />
      </div>
    );
  }

  const isAuthenticated = authStatus.old && authStatus.new;

  if (!isAuthenticated) {
    return <LandingView authStatus={authStatus} />;
  }

  return <WorkbenchView />;
}

function LandingView({ authStatus }: { authStatus: { old: boolean; new: boolean } }) {
  return (
    <div className="min-h-screen bg-paper-1 flex flex-col items-center justify-center p-6">
      <div className="max-w-2xl w-full text-center space-y-8">
        <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-paper-2 border border-border shadow-sm mb-4">
          <Disc className="w-8 h-8 text-accent" />
        </div>
        
        <h1 className="text-4xl md:text-5xl font-medium tracking-tight text-balance">
          Merge your Spotify libraries without the heavy lifting.
        </h1>
        
        <p className="text-lg text-text-dim text-pretty max-w-xl mx-auto">
          Connect your old and new accounts. We'll automatically identify duplicates, map your playlists, and safely migrate your entire catalog.
        </p>

        <div className="grid md:grid-cols-2 gap-4 mt-12 max-w-lg mx-auto">
          <a
            href={authStatus.old ? "#" : "/api/auth/old/login"}
            className={`flex items-center justify-between p-4 rounded-xl border transition-all ${
              authStatus.old 
                ? "bg-paper-2 border-border text-text-dim cursor-default"
                : "bg-paper-1 border-border hover:border-accent hover:shadow-sm"
            }`}
          >
            <div className="flex items-center gap-3">
              <div className={`w-3 h-3 rounded-full ${authStatus.old ? 'bg-green-500' : 'bg-border'}`} />
              <span className="font-medium">{authStatus.old ? "Old Account Linked" : "Connect Old Account"}</span>
            </div>
            {!authStatus.old && <ArrowRight className="w-4 h-4 text-text-dim" />}
          </a>

          <a
            href={authStatus.new ? "#" : "/api/auth/new/login"}
            className={`flex items-center justify-between p-4 rounded-xl border transition-all ${
              authStatus.new 
                ? "bg-paper-2 border-border text-text-dim cursor-default"
                : "bg-paper-1 border-border hover:border-accent hover:shadow-sm"
            }`}
          >
            <div className="flex items-center gap-3">
              <div className={`w-3 h-3 rounded-full ${authStatus.new ? 'bg-green-500' : 'bg-border'}`} />
              <span className="font-medium">{authStatus.new ? "New Account Linked" : "Connect New Account"}</span>
            </div>
            {!authStatus.new && <ArrowRight className="w-4 h-4 text-text-dim" />}
          </a>
        </div>
      </div>
    </div>
  );
}

function WorkbenchView() {
  return (
    <div className="min-h-screen bg-paper-1 flex flex-col md:flex-row">
      {/* Sidebar N3-ish Rail */}
      <aside className="w-full md:w-64 border-r border-border bg-paper-2 p-4 flex flex-col gap-6 shrink-0">
        <div className="flex items-center gap-3 font-medium px-2 pt-2">
          <Disc className="w-5 h-5 text-accent" />
          <span>Migrator</span>
        </div>
        
        <nav className="flex flex-col gap-1">
          <button className="flex items-center gap-3 px-3 py-2 rounded-lg bg-paper-3 text-sm font-medium transition-colors">
            <ListMusic className="w-4 h-4" />
            Library Sync
          </button>
        </nav>
      </aside>

      {/* Canvas */}
      <main className="flex-1 flex flex-col p-6 md:p-10 max-h-screen overflow-y-auto">
        <header className="mb-8">
          <h2 className="text-2xl font-medium tracking-tight">Library Workspace</h2>
          <p className="text-text-dim mt-1 text-sm">Both accounts connected. Ready to sync and merge.</p>
        </header>

        <div className="flex-1 border border-border rounded-2xl bg-paper-2 border-dashed flex items-center justify-center p-8">
          <div className="text-center max-w-sm">
            <h3 className="font-medium mb-2">Sync needed</h3>
            <p className="text-sm text-text-dim mb-6">
              We need to fetch the local representation of both libraries before running the merge comparison.
            </p>
            <button className="bg-foreground text-background px-5 py-2.5 rounded-full text-sm font-medium hover:opacity-90 transition-opacity">
              Start full library sync
            </button>
          </div>
        </div>
      </main>
    </div>
  );
}
