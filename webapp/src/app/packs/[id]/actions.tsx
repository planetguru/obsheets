"use client";

export default function PackActions({ id }: { id: string }) {
  function print() {
    const frame = document.getElementById("packframe") as HTMLIFrameElement | null;
    frame?.contentWindow?.print();
  }
  return (
    <div className="actions">
      <button className="btn" onClick={print}>
        Print
      </button>
      <a className="btn alt" href={`/api/packs/${id}/html?download=1`}>
        Download HTML
      </a>
      <a className="btn subtle" href={`/api/packs/${id}/html`} target="_blank">
        Open in new tab
      </a>
    </div>
  );
}
