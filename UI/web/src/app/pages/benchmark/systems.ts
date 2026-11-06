/** The systems a benchmark run compares and their names, as Benchmark/bench/systems.py defines them, in the order the
 *  benchmark pages show them. This is the one place those pages take them from; a run's own list is in its config
 *  (systems_compared). */
export const SYSTEMS = ['rag', 'rag_q', 'wiki'];
export const LABEL: Record<string, string> = { rag: 'RAG (per topic)', rag_q: 'RAG (per question)', wiki: 'Wiki' };
export const SHORT: Record<string, string> = { rag: 'RAG topic', rag_q: 'RAG question', wiki: 'Wiki' };
