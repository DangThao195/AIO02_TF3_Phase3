-- Step 1: Add is_safe column to reviews.productreviews if it does not exist
ALTER TABLE reviews.productreviews ADD COLUMN IF NOT EXISTS is_safe BOOLEAN DEFAULT TRUE;

-- Step 2: Create composite index for optimized lookups by product_id and is_safe
CREATE INDEX IF NOT EXISTS productreviews_prod_safe_idx ON reviews.productreviews (product_id, is_safe);

-- Step 3: Create reviews.fidelity_audit table for asynchronous audit logging
CREATE TABLE IF NOT EXISTS reviews.fidelity_audit (
    id SERIAL PRIMARY KEY,
    product_id VARCHAR(50) NOT NULL,
    model VARCHAR(100) NOT NULL,
    approved BOOLEAN NOT NULL,
    input_tokens INT NOT NULL,
    output_tokens INT NOT NULL,
    response TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Step 4: Grant permissions to otelu user
GRANT SELECT, INSERT, UPDATE ON reviews.fidelity_audit TO otelu;


