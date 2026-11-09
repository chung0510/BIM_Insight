import {useEffect, useRef, type ReactNode} from "react";
import {X} from "lucide-react";

export default function Dialog({title, onClose, children}: {title: string; onClose: () => void; children: ReactNode}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { ref.current?.showModal(); }, []);
  return <dialog ref={ref} className="dialog dialog-wide" aria-label={title} onCancel={event => { event.preventDefault(); onClose(); }} onClick={event => { if (event.target === event.currentTarget) onClose(); }}><header className="dialog-header"><h2>{title}</h2><button className="icon-button" aria-label="Đóng cửa sổ" onClick={onClose}><X size={20} /></button></header>{children}</dialog>;
}
