type HermesSuggestionsProps = {
  suggestions: unknown[];
};

export function HermesSuggestions({ suggestions }: HermesSuggestionsProps) {
  return (
    <section className="rounded-md border border-stone-200 bg-white">
      <div className="border-b border-stone-200 px-4 py-3">
        <h2 className="text-base font-semibold text-ink">Hermes</h2>
      </div>
      <div className="max-h-52 overflow-auto p-3">
        {suggestions.length === 0 ? (
          <div className="text-sm text-stone-500">No suggestions yet</div>
        ) : (
          <pre className="whitespace-pre-wrap break-words text-xs text-stone-700">
            {JSON.stringify(suggestions, null, 2)}
          </pre>
        )}
      </div>
    </section>
  );
}
