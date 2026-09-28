/** Placeholders the backend substitutes for PII, e.g. <MEMBER_ID> or <EMAIL>. */
const MASK_SPLIT = /(<[A-Z][A-Z0-9_]*>)/;
const MASK_TOKEN = /^<[A-Z][A-Z0-9_]*>$/;

/** Renders text with masked-PII placeholders visually set apart from real values. */
export function MaskedText({ text }: { text: string }) {
  return (
    <>
      {text.split(MASK_SPLIT).map((part, i) =>
        MASK_TOKEN.test(part) ? (
          <span key={i} className="masked-token">
            {part}
          </span>
        ) : (
          part
        ),
      )}
    </>
  );
}
