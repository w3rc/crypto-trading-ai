import { Component, type ReactNode } from "react";

type Props = { children: ReactNode };
type State = { error: Error | null };

// Renderer error boundary: a crash in one view shows a fallback instead of
// white-screening the whole app. Wrapped with key={view} in App so switching
// tabs (the sidebar stays outside the boundary) remounts it and clears the error.
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error): void {
    console.error("view crashed:", error);
  }

  render(): ReactNode {
    if (this.state.error) {
      return (
        <section className="card error-fallback">
          <h2>This view hit an error</h2>
          <p className="muted">The rest of the dashboard still works — switch tabs in the sidebar, or reload.</p>
          <pre>{this.state.error.message}</pre>
          <button className="bt-run" onClick={() => location.reload()}>Reload</button>
        </section>
      );
    }
    return this.props.children;
  }
}
