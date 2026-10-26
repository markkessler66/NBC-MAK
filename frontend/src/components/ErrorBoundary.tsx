import { Component, type ReactNode } from "react";

interface Props {
  label: string;
  children: ReactNode;
}

interface State {
  error: Error | null;
}

/** Contains a crashing panel instead of letting it unmount the whole app. */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  render() {
    if (this.state.error) {
      return (
        <div className="card p-4 border-rose-500/40">
          <div className="card-title text-rose-300 mb-2">{this.props.label} crashed</div>
          <div className="text-xs text-rose-200/90 font-mono break-all">
            {this.state.error.message}
          </div>
          <button
            onClick={() => this.setState({ error: null })}
            className="mt-3 px-2.5 py-1 text-xs rounded border bg-slate-800 border-slate-700 text-slate-300 hover:text-slate-100"
          >
            Retry
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
