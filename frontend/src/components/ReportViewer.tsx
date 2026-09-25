"use client";
import { useEffect, useState } from "react";
import { download, fetchBlob } from "@/lib/api";
import { ErrorText, Spinner } from "./ui";

/** Shows an HTML report inside a sandboxed iframe (no scripts, no same-origin access). */
export default function ReportViewer({ htmlPath, pdfPath, pdfName, canExport, onClose }: {
  htmlPath: string; pdfPath: string; pdfName: string; canExport: boolean; onClose: () => void;
}) {
  const [html, setHtml] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => { fetchBlob(htmlPath).then((b) => b.text()).then(setHtml).catch(setError); }, [htmlPath]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="modal-back" onClick={onClose}>
      <div className="modal" role="dialog" aria-modal="true" aria-label="Report" onClick={(e) => e.stopPropagation()}>
        <header>
          <b>Report</b>
          <div className="row">
            {canExport && <button onClick={() => download(pdfPath, pdfName).catch(setError)}>Download PDF (audited)</button>}
            <button onClick={onClose}>Close</button>
          </div>
        </header>
        <ErrorText error={error} />
        {html === null && !error ? <div style={{ padding: 16 }}><Spinner label="Generating report…" /></div>
          : html !== null && <iframe title="Report" sandbox="" srcDoc={html} />}
      </div>
    </div>
  );
}
